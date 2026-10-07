// SPDX-License-Identifier: GPL-2.0-only
/* Native TL64 GMAC + single-descriptor coherent packet DMA, ABI v1.
 * Bring-up driver: DMA IRQ + budgeted NAPI, 1G/full duplex, no offloads.
 * DMA has no abort/reset register. Buffers remain allocated across ifdown;
 * this module deliberately has no exit callback or sysfs unbind operation.
 * Reset the board to remove it. Never free an armed RX buffer.
 */
#include "valence_driver_names.h"
#define pr_fmt(fmt) VALENCE_GMAC_DRIVER ": " fmt
#include <linux/delay.h>
#include <linux/clk.h>
#include <linux/dma-mapping.h>
#include <linux/etherdevice.h>
#include <linux/ethtool.h>
#include <linux/io.h>
#include <linux/interrupt.h>
#include <linux/iopoll.h>
#include <linux/ktime.h>
#include <linux/module.h>
#include <linux/of_address.h>
#include <linux/of_mdio.h>
#include <linux/of_net.h>
#include <linux/phy.h>
#include <linux/platform_device.h>
#include <linux/workqueue.h>
#include "valence_irq_policy.h"

#define GMAC_ID 0x56474d4100010001ULL
#define DMA_ID  0x56444d4100010001ULL
#define FRAME_BYTES 2048
#define G_CAP 0x08
#define G_CAP_RX_STOP BIT_ULL(8)
#define G_CONTROL 0x10
#define G_ADDRESS 0x18
#define G_STATUS 0x28
#define G_IRQ_ENABLE 0x38
#define G_MDIO_COMMAND 0x78
#define G_MDIO_STATUS 0x80
#define G_MDIO_RESULT 0x88
#define G_RX_STOP 0x90
#define D_IRQ_ENABLE 0x08
#define D_TX_ADDRESS 0x10
#define D_TX_LENGTH 0x18
#define D_TX_COMMAND 0x20
#define D_TX_STATUS 0x28
#define D_RX_ADDRESS 0x30
#define D_RX_CAPACITY 0x38
#define D_RX_COMMAND 0x40
#define D_RX_STATUS 0x48
#define D_RX_LENGTH 0x50
#define D_BUSY BIT_ULL(0)
#define D_DONE BIT_ULL(1)
#define D_ERROR BIT_ULL(2)

struct vgmac {
	struct net_device *ndev;
	void __iomem *mac, *dma;
	struct mii_bus *bus;
	struct delayed_work configure;
	struct napi_struct napi;
	int irq;
	spinlock_t lock;
	void *tx_buffer, *rx_buffer;
	dma_addr_t tx_address, rx_address;
	u64 hw_address;
	u64 ram_base, ram_bytes;
	unsigned int tx_length;
	u64 interrupts, napi_polls, rx_work, empty_polls;
	bool running, address_set, configured, tx_pending, faulted;
};

static u64 vg_read(void __iomem *base, unsigned int offset)
{
	return readq(base + offset);
}

static void vg_write(void __iomem *base, unsigned int offset, u64 value)
{
	/* The packet DMA and MDIO launch REQUIRE a single full-width access. */
	writeq(value, base + offset);
}

static int vg_mdio(struct mii_bus *bus, int phy, int reg, bool write, u16 data)
{
	struct vgmac *p = bus->priv;
	u64 status;
	int ret;

	ret = read_poll_timeout(vg_read, status, !(status & 1), 50, 20000,
				false, p->mac, G_MDIO_STATUS);
	if (ret)
		return ret;
	vg_write(p->mac, G_MDIO_COMMAND, data | ((u64)write << 16) |
		 BIT_ULL(17) | ((u64)(phy & 31) << 18) | ((u64)(reg & 31) << 23));
	ret = read_poll_timeout(vg_read, status, (status & 3) == 2, 50, 20000,
				false, p->mac, G_MDIO_STATUS);
	if (ret)
		return ret;
	status = vg_read(p->mac, G_MDIO_RESULT);
	return status & BIT_ULL(16) ? -EIO : (write ? 0 : (int)(status & 0xffff));
}

static int vg_mdio_read(struct mii_bus *bus, int phy, int reg)
{
	return vg_mdio(bus, phy, reg, false, 0);
}

static int vg_mdio_write(struct mii_bus *bus, int phy, int reg, u16 data)
{
	return vg_mdio(bus, phy, reg, true, data);
}

static void vg_adjust_link(struct net_device *ndev)
{
	struct vgmac *p = netdev_priv(ndev);
	struct phy_device *phy = ndev->phydev;

	if (phy->link && phy->speed == SPEED_1000 && phy->duplex == DUPLEX_FULL) {
		netif_carrier_on(ndev);
		if (READ_ONCE(p->running) && READ_ONCE(p->configured) && !READ_ONCE(p->tx_pending) &&
		    !READ_ONCE(p->faulted))
			netif_wake_queue(ndev);
		if (READ_ONCE(p->running) && !READ_ONCE(p->configured))
			mod_delayed_work(system_wq, &p->configure, 0);
	} else {
		netif_carrier_off(ndev);
		netif_stop_queue(ndev);
	}
	phy_print_status(phy);
}

static int vg_delays(struct net_device *ndev)
{
	int tx = phy_read_paged(ndev->phydev, 0xd08, 0x11);
	int rx = phy_read_paged(ndev->phydev, 0xd08, 0x15);

	if (tx < 0 || rx < 0)
		return tx < 0 ? tx : rx;
	if ((tx & BIT(8)) || !(rx & BIT(3))) {
		netdev_err(ndev, "unsafe RGMII delay: TXCR=%04x RXCR=%04x\n", tx, rx);
		return -EINVAL;
	}
	netdev_info(ndev, "RTL8211F delay verified: TXDLY=0 RXDLY=1 (FPGA TX +2ns)\n");
	return 0;
}

static void vg_arm_rx(struct vgmac *p)
{
	/* Caller proved !BUSY. RX buffer is permanently DMA-addressable. */
	/* The descriptor address/capacity persist and were programmed at probe. */
	dma_wmb();
	vg_write(p->dma, D_RX_COMMAND, 3); /* acknowledge, then start */
}

static void vg_configure(struct work_struct *work)
{
	struct vgmac *p = container_of(to_delayed_work(work), struct vgmac, configure);
	struct net_device *ndev = p->ndev;
	bool retry = false, start = false;

	spin_lock_bh(&p->lock);
	if (!p->running)
		goto unlock;
	/* RX media/config CDC can be held until the PHY produces a 125MHz
	 * clock. Let phylib negotiate first; ifup must also work unplugged.
	 * RX is disabled during these two once-only configuration writes. */
	if (!p->configured) {
		if (!netif_carrier_ok(ndev) || (vg_read(p->mac, G_STATUS) & 6)) {
			retry = true;
			goto unlock;
		}
		if (!p->address_set) {
			vg_write(p->mac, G_ADDRESS, p->hw_address);
			p->address_set = true;
			retry = true;
			goto unlock; /* wait for both config CDC acknowledgements */
		}
		/* BootROM ABI v2 leaves RX admission stopped at handoff. Install a
		 * live consumer before releasing it, then enable the MAC. Legacy
		 * hardware has no such register: never write its reserved offset. */
		if (vg_read(p->dma, D_RX_STATUS) & D_BUSY) {
			retry = true;
			goto unlock;
		}
		vg_arm_rx(p);
		if (vg_read(p->mac, G_CAP) & G_CAP_RX_STOP)
			vg_write(p->mac, G_RX_STOP, 0);
		vg_write(p->mac, G_CONTROL, 15);
		p->configured = true;
		if (!p->tx_pending && !p->faulted)
			netif_wake_queue(ndev);
	}
	start = !p->faulted;
unlock:
	spin_unlock_bh(&p->lock);
	if (!READ_ONCE(p->running))
		return;
	if (retry)
		schedule_delayed_work(&p->configure, msecs_to_jiffies(100));
	else if (start)
		napi_schedule(&p->napi);
	/* No periodic data-plane worker after once-only MAC configuration. */
}

static irqreturn_t vg_irq(int irq, void *data)
{
	struct net_device *ndev = data;
	struct vgmac *p = netdev_priv(ndev);

	/* No p->lock in hard IRQ: process/NAPI contexts hold it with BH disabled.
	 * Mask the device BEFORE scheduling; completion remains latched in DMA. */
	vg_write(p->dma, D_IRQ_ENABLE, 0);
	p->interrupts++;
	if (vg_irq_allowed(READ_ONCE(p->running), READ_ONCE(p->configured), READ_ONCE(p->faulted)))
		napi_schedule_irqoff(&p->napi);
	return IRQ_HANDLED;
}

static int vg_napi_poll(struct napi_struct *napi, int budget)
{
	struct vgmac *p = container_of(napi, struct vgmac, napi);
	struct net_device *ndev = p->ndev;
	u64 deadline = ktime_get_ns() + VG_NAPI_TIME_NS;
	u64 tx, rx, bytes;
	int work = 0;
	bool active;

	p->napi_polls++;
	spin_lock_bh(&p->lock);
	active = vg_irq_allowed(p->running, p->configured, p->faulted);
	/* Do not read an idle TX engine. TX completion is independent of RX budget. */
	if (active && p->tx_pending) {
		tx = vg_read(p->dma, D_TX_STATUS);
		if ((tx & D_DONE) && !(tx & D_BUSY)) {
			dma_rmb();
			if (tx & D_ERROR) {
				ndev->stats.tx_errors++;
			} else {
				ndev->stats.tx_packets++;
				ndev->stats.tx_bytes += p->tx_length;
			}
			vg_write(p->dma, D_TX_COMMAND, 2);
			p->tx_pending = false;
			if (netif_carrier_ok(ndev) && !p->faulted)
				netif_wake_queue(ndev);
		}
	}
	spin_unlock_bh(&p->lock);
	while (active && work < budget) {
		struct sk_buff *skb = NULL;

		spin_lock_bh(&p->lock);
		active = vg_irq_allowed(p->running, p->configured, p->faulted);
		if (!active) {
			spin_unlock_bh(&p->lock);
			break;
		}
		rx = vg_read(p->dma, D_RX_STATUS);
		if ((rx & D_BUSY) || !(rx & D_DONE)) {
			if (!(rx & D_BUSY))
				vg_arm_rx(p);
			spin_unlock_bh(&p->lock);
			break; /* Never spin waiting for hardware to finish. */
		}
		bytes = vg_read(p->dma, D_RX_LENGTH);
		dma_rmb();
		if ((rx & D_ERROR) || bytes < ETH_HLEN || bytes > FRAME_BYTES) {
			ndev->stats.rx_errors++;
		} else {
			skb = napi_alloc_skb(napi, bytes);
			if (skb) {
				memcpy(skb_put(skb, bytes), p->rx_buffer, bytes);
				skb->protocol = eth_type_trans(skb, ndev);
				skb->ip_summed = CHECKSUM_NONE;
				ndev->stats.rx_packets++;
				ndev->stats.rx_bytes += bytes;
			} else {
				ndev->stats.rx_dropped++;
			}
		}
		vg_arm_rx(p);
		spin_unlock_bh(&p->lock);
		work++;
		p->rx_work++;
		if (skb)
			napi_gro_receive(napi, skb);
		if (ktime_get_ns() >= deadline)
			return budget; /* Leave IRQ masked; core budget yields to other tasks. */
	}
	if (!work)
		p->empty_polls++;
	/* A zero budget can be a TX-only call; it must not complete NAPI. */
	if (budget && work < budget && napi_complete_done(napi, work)) {
		spin_lock_bh(&p->lock);
		if (vg_irq_allowed(p->running, p->configured, p->faulted))
			vg_write(p->dma, D_IRQ_ENABLE, 3);
		/* DONE is latched: arrivals during completion/unmask raise a fresh IRQ. */
		spin_unlock_bh(&p->lock);
	}
	return work;
}

static netdev_tx_t vg_xmit(struct sk_buff *skb, struct net_device *ndev)
{
	struct vgmac *p = netdev_priv(ndev);
	u64 status;

	spin_lock_bh(&p->lock);
	status = vg_read(p->dma, D_TX_STATUS);
	if (!p->running || !p->configured || p->faulted || p->tx_pending || (status & D_BUSY)) {
		netif_stop_queue(ndev);
		spin_unlock_bh(&p->lock);
		return NETDEV_TX_BUSY;
	}
	if (skb->len < ETH_HLEN || skb->len > FRAME_BYTES ||
	    skb_copy_bits(skb, 0, p->tx_buffer, skb->len)) {
		ndev->stats.tx_dropped++;
		spin_unlock_bh(&p->lock);
		dev_kfree_skb_any(skb);
		return NETDEV_TX_OK;
	}
	netif_stop_queue(ndev);
	p->tx_pending = true;
	p->tx_length = skb->len;
	dma_wmb();
	/* Persistent TX address was programmed at probe; only length changes. */
	vg_write(p->dma, D_TX_LENGTH, skb->len);
	vg_write(p->dma, D_TX_COMMAND, 3);
	netif_trans_update(ndev);
	spin_unlock_bh(&p->lock);
	dev_kfree_skb_any(skb); /* copied payload, not the skb, is DMA-owned */
	return NETDEV_TX_OK;
}

static int vg_open(struct net_device *ndev)
{
	struct vgmac *p = netdev_priv(ndev);
	int ret;

	ret = vg_delays(ndev);
	if (ret)
		return ret;
	napi_enable(&p->napi);
	spin_lock_bh(&p->lock);
	p->running = true;
	spin_unlock_bh(&p->lock);
	netif_carrier_off(ndev);
	netif_start_queue(ndev);
	netif_stop_queue(ndev);
	phy_start(ndev->phydev);
	schedule_delayed_work(&p->configure, 0);
	return 0;
}

static int vg_stop(struct net_device *ndev)
{
	struct vgmac *p = netdev_priv(ndev);

	netif_stop_queue(ndev);
	spin_lock_bh(&p->lock);
	p->running = false;
	vg_write(p->dma, D_IRQ_ENABLE, 0);
	spin_unlock_bh(&p->lock);
	cancel_delayed_work_sync(&p->configure);
	synchronize_irq(p->irq);
	napi_disable(&p->napi);
	phy_stop(ndev->phydev);
	netif_carrier_off(ndev);
	/* Hardware has no cancel. Keep buffers and MAC configuration intact;
	 * completion is consumed on the next ifup, never ACK a BUSY engine. */
	return 0;
}

static void vg_timeout(struct net_device *ndev, unsigned int queue)
{
	struct vgmac *p = netdev_priv(ndev);

	WRITE_ONCE(p->faulted, true);
	vg_write(p->dma, D_IRQ_ENABLE, 0);
	netif_stop_queue(ndev);
	netdev_err(ndev, "DMA timeout: TX=%llx RX=%llx; reset board, no unsafe forced cancel\n",
		   vg_read(p->dma, D_TX_STATUS), vg_read(p->dma, D_RX_STATUS));
}

static const struct net_device_ops vg_ops = {
	.ndo_open = vg_open,
	.ndo_stop = vg_stop,
	.ndo_start_xmit = vg_xmit,
	.ndo_tx_timeout = vg_timeout,
	.ndo_validate_addr = eth_validate_addr,
};

static void vg_drvinfo(struct net_device *ndev, struct ethtool_drvinfo *info)
{
	strscpy(info->driver, VALENCE_GMAC_DRIVER, sizeof(info->driver));
	strscpy(info->version, VALENCE_DRIVER_VERSION, sizeof(info->version));
}

static const struct ethtool_ops vg_ethtool = {
	.get_drvinfo = vg_drvinfo,
	.get_link = ethtool_op_get_link,
	.get_link_ksettings = phy_ethtool_get_link_ksettings,
};

static bool vg_dma_address_ok(struct vgmac *p, dma_addr_t address)
{
	return !(address & 7) && address >= p->ram_base &&
	       address - p->ram_base <= p->ram_bytes - FRAME_BYTES;
}

static ssize_t napi_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct net_device *ndev = dev_get_drvdata(dev);
	struct vgmac *p = netdev_priv(ndev);

	return sysfs_emit(buf, "irq=%d interrupts=%llu napi_polls=%llu rx_work=%llu empty_polls=%llu running=%u configured=%u faulted=%u\n",
			  p->irq, READ_ONCE(p->interrupts), READ_ONCE(p->napi_polls),
			  READ_ONCE(p->rx_work), READ_ONCE(p->empty_polls), READ_ONCE(p->running),
			  READ_ONCE(p->configured), READ_ONCE(p->faulted));
}
static DEVICE_ATTR_RO(napi_status);
static struct attribute *vg_attrs[] = { &dev_attr_napi_status.attr, NULL };
static const struct attribute_group vg_group = { .attrs = vg_attrs };

static int vg_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct device_node *mdio, *phy;
	struct net_device *ndev;
	struct vgmac *p;
	u8 address[ETH_ALEN];
	u64 mac_address = 0;
	phy_interface_t interface;
	struct clk *clock;
	int i, ret;

	ndev = alloc_etherdev(sizeof(*p));
	if (!ndev)
		return -ENOMEM;
	SET_NETDEV_DEV(ndev, dev);
	p = netdev_priv(ndev);
	p->ndev = ndev;
	p->ram_base = 0x80200000ULL;
	p->ram_bytes = 0x20000000ULL;
	of_property_read_u64(dev->of_node, "openion,ram-base", &p->ram_base);
	of_property_read_u64(dev->of_node, "openion,ram-bytes", &p->ram_bytes);
	if (p->ram_base != 0x80200000ULL || p->ram_bytes < FRAME_BYTES ||
	    p->ram_bytes > 0x80000000ULL) {
		ret = -EINVAL;
		goto free_net;
	}
	clock = devm_clk_get_optional_enabled(dev, "tx");
	if (IS_ERR(clock)) {
		ret = PTR_ERR(clock);
		goto free_net;
	}
	clock = devm_clk_get_optional_enabled(dev, "rx");
	if (IS_ERR(clock)) {
		ret = PTR_ERR(clock);
		goto free_net;
	}
	spin_lock_init(&p->lock);
	INIT_DELAYED_WORK(&p->configure, vg_configure);
	p->irq = platform_get_irq(pdev, 0);
	if (p->irq < 0) {
		ret = p->irq;
		goto free_net;
	}
	ret = of_get_phy_mode(dev->of_node, &interface);
	if (ret || interface != PHY_INTERFACE_MODE_RGMII_RXID) {
		ret = -EINVAL;
		goto free_net;
	}
	if (!of_dma_is_coherent(dev->of_node)) {
		dev_err(dev, "coherent CPU/DMA boundary must be described in DT\n");
		ret = -EINVAL;
		goto free_net;
	}
	p->mac = devm_platform_ioremap_resource(pdev, 0);
	p->dma = devm_platform_ioremap_resource(pdev, 1);
	if (IS_ERR(p->mac) || IS_ERR(p->dma)) {
		ret = IS_ERR(p->mac) ? PTR_ERR(p->mac) : PTR_ERR(p->dma);
		goto free_net;
	}
	if (vg_read(p->mac, 0) != GMAC_ID || vg_read(p->dma, 0) != DMA_ID ||
	    vg_read(p->dma, 0x88) != FRAME_BYTES) {
		ret = -ENODEV;
		goto free_net;
	}
	if ((vg_read(p->dma, D_TX_STATUS) | vg_read(p->dma, D_RX_STATUS)) & D_BUSY ||
	    vg_read(p->mac, G_CONTROL) & 3) {
		dev_err(dev, "reset required: MAC/DMA already active\n");
		ret = -EBUSY;
		goto free_net;
	}
	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(64));
	if (ret)
		goto free_net;
	p->tx_buffer = dma_alloc_coherent(dev, FRAME_BYTES, &p->tx_address, GFP_KERNEL);
	p->rx_buffer = dma_alloc_coherent(dev, FRAME_BYTES, &p->rx_address, GFP_KERNEL);
	if (!p->tx_buffer || !p->rx_buffer || !vg_dma_address_ok(p, p->tx_address) ||
	    !vg_dma_address_ok(p, p->rx_address)) {
		ret = -ENOMEM;
		goto free_buffers;
	}
	vg_write(p->dma, D_IRQ_ENABLE, 0);
	vg_write(p->mac, G_IRQ_ENABLE, 0);
	vg_write(p->dma, D_TX_ADDRESS, p->tx_address);
	vg_write(p->dma, D_RX_ADDRESS, p->rx_address);
	vg_write(p->dma, D_RX_CAPACITY, FRAME_BYTES);
	if (!of_get_mac_address(dev->of_node, address))
		eth_hw_addr_set(ndev, address);
	else
		eth_hw_addr_random(ndev);
	for (i = 0; i < ETH_ALEN; i++)
		mac_address = (mac_address << 8) | ndev->dev_addr[i];
	p->hw_address = mac_address;
	p->bus = mdiobus_alloc();
	if (!p->bus) {
		ret = -ENOMEM;
		goto free_buffers;
	}
	p->bus->name = "valence-mdio";
	p->bus->parent = dev;
	p->bus->priv = p;
	p->bus->read = vg_mdio_read;
	p->bus->write = vg_mdio_write;
	snprintf(p->bus->id, MII_BUS_ID_SIZE, "%s", dev_name(dev));
	mdio = of_get_child_by_name(dev->of_node, "mdio");
	if (!mdio) {
		ret = -EINVAL;
		goto free_bus;
	}
	ret = of_mdiobus_register(p->bus, mdio);
	of_node_put(mdio);
	if (ret)
		goto free_bus;
	phy = of_parse_phandle(dev->of_node, "phy-handle", 0);
	if (!of_phy_connect(ndev, phy, vg_adjust_link, 0, PHY_INTERFACE_MODE_RGMII_RXID)) {
		of_node_put(phy);
		ret = -ENODEV;
		goto unregister_bus;
	}
	of_node_put(phy);
	if (ndev->phydev->phy_id != 0x001cc916) {
		dev_err(dev, "expected RTL8211F, got PHY %08x\n", ndev->phydev->phy_id);
		ret = -ENODEV;
		goto disconnect;
	}
	phy_remove_link_mode(ndev->phydev, ETHTOOL_LINK_MODE_10baseT_Half_BIT);
	phy_remove_link_mode(ndev->phydev, ETHTOOL_LINK_MODE_10baseT_Full_BIT);
	phy_remove_link_mode(ndev->phydev, ETHTOOL_LINK_MODE_100baseT_Half_BIT);
	phy_remove_link_mode(ndev->phydev, ETHTOOL_LINK_MODE_100baseT_Full_BIT);
	phy_remove_link_mode(ndev->phydev, ETHTOOL_LINK_MODE_1000baseT_Half_BIT);
	phy_remove_link_mode(ndev->phydev, ETHTOOL_LINK_MODE_Pause_BIT);
	phy_remove_link_mode(ndev->phydev, ETHTOOL_LINK_MODE_Asym_Pause_BIT);
	ndev->netdev_ops = &vg_ops;
	ndev->ethtool_ops = &vg_ethtool;
	ndev->watchdog_timeo = 2 * HZ;
	ndev->min_mtu = 68;
	ndev->max_mtu = 1500;
	netif_napi_add_weight(ndev, &p->napi, vg_napi_poll, VG_NAPI_WEIGHT);
	ret = request_irq(p->irq, vg_irq, 0, "valence-gmac-dma", ndev);
	if (ret)
		goto delete_napi;
	ret = register_netdev(ndev);
	if (ret)
		goto free_irq;
	platform_set_drvdata(pdev, ndev);
	ret = devm_device_add_group(dev, &vg_group);
	if (ret) {
		unregister_netdev(ndev);
		goto free_irq;
	}
	phy_attached_info(ndev->phydev);
	dev_info(dev, "%s: native GMAC + coherent DMA, IRQ %d / NAPI weight %u, MAC %pM\n",
		 ndev->name, p->irq, VG_NAPI_WEIGHT, ndev->dev_addr);
	return 0;
free_irq:
	free_irq(p->irq, ndev);
delete_napi:
	netif_napi_del(&p->napi);
disconnect:
	phy_disconnect(ndev->phydev);
unregister_bus:
	mdiobus_unregister(p->bus);
free_bus:
	mdiobus_free(p->bus);
free_buffers:
	if (p->rx_buffer)
		dma_free_coherent(dev, FRAME_BYTES, p->rx_buffer, p->rx_address);
	if (p->tx_buffer)
		dma_free_coherent(dev, FRAME_BYTES, p->tx_buffer, p->tx_address);
free_net:
	free_netdev(ndev);
	return ret;
}

static const struct of_device_id vg_match[] = {
	{ .compatible = "openion,valence-native-gmac-v1" }, { }
};
MODULE_DEVICE_TABLE(of, vg_match);
static struct platform_driver vg_driver = {
	.probe = vg_probe,
	.driver = {
		.name = VALENCE_GMAC_DRIVER,
		.of_match_table = vg_match,
		.suppress_bind_attrs = true,
	},
};
static int __init vg_init(void)
{
	return platform_driver_register(&vg_driver);
}
module_init(vg_init);
MODULE_DESCRIPTION("Valence native TL GMAC + coherent packet DMA bring-up");
MODULE_AUTHOR(VALENCE_VENDOR);
MODULE_VERSION(VALENCE_DRIVER_VERSION);
MODULE_LICENSE("GPL");
