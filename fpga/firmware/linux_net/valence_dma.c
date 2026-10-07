// SPDX-License-Identifier: GPL-2.0-only
/* Single-channel, four-credit aligned memcpy DMAengine provider and explicit
 * bandwidth-test client. No SG, memcpy tails, overlap, or hardware abort.
 * A timed-out active engine keeps its channel/buffers until board reset.
 */
#define pr_fmt(fmt) "valence-dma: " fmt
#include <linux/completion.h>
#include <linux/dma-mapping.h>
#include <linux/io.h>
#include <linux/ktime.h>
#include <linux/math64.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of_dma.h>
#include <linux/of_address.h>
#include <linux/platform_device.h>
#include "virt-dma.h"
#include "valence_driver_names.h"

#define VD_CONTROL 0x18
#define VD_STATUS 0x20
#define VD_BUSY BIT_ULL(0)
#define VD_DONE BIT_ULL(1)
#define VD_ERROR BIT_ULL(2)

struct vdesc {
	struct virt_dma_desc vd;
	dma_addr_t source, destination;
	size_t length;
};
struct vdma {
	struct dma_device dma;
	struct virt_dma_chan vc;
	struct device *dev;
	void __iomem *regs;
	struct vdesc *active;
	u64 base, bytes, interrupts, completed;
	dma_cookie_t failed_cookie;
	bool faulted;
};

static struct vdma *vd_chan(struct dma_chan *chan)
{
	return container_of(to_virt_chan(chan), struct vdma, vc);
}
static struct vdesc *vd_desc(struct virt_dma_desc *vd)
{
	return container_of(vd, struct vdesc, vd);
}
static bool vd_range(struct vdma *p, dma_addr_t address, size_t length)
{
	return length && !(address & 7) && !(length & 7) && length <= p->bytes &&
		address >= p->base && address - p->base <= p->bytes - length;
}
static void vd_free(struct virt_dma_desc *vd) { kfree(vd_desc(vd)); }

static struct dma_async_tx_descriptor *vd_prep(struct dma_chan *chan,
		dma_addr_t destination, dma_addr_t source, size_t length, unsigned long flags)
{
	struct vdma *p = vd_chan(chan);
	struct vdesc *desc;

	if (READ_ONCE(p->faulted) || !vd_range(p, source, length) || !vd_range(p, destination, length) ||
	    (destination < source + length && source < destination + length))
		return NULL;
	desc = kzalloc(sizeof(*desc), GFP_NOWAIT);
	if (!desc)
		return NULL;
	desc->source = source;
	desc->destination = destination;
	desc->length = length;
	return vchan_tx_prep(&p->vc, &desc->vd, flags);
}

static void vd_start(struct vdma *p)
{
	struct virt_dma_desc *vd;

	lockdep_assert_held(&p->vc.lock);
	if (p->active || p->faulted)
		return;
	vd = vchan_next_desc(&p->vc);
	if (!vd)
		return;
	list_del(&vd->node);
	p->active = vd_desc(vd);
	writeq(p->active->source, p->regs);
	writeq(p->active->destination, p->regs + 8);
	writeq(p->active->length, p->regs + 16);
	dma_wmb();
	writeq(7, p->regs + VD_CONTROL); /* START | ACK old DONE | IRQ */
}
static void vd_issue(struct dma_chan *chan)
{
	struct vdma *p = vd_chan(chan);
	unsigned long flags;

	spin_lock_irqsave(&p->vc.lock, flags);
	if (vchan_issue_pending(&p->vc))
		vd_start(p);
	spin_unlock_irqrestore(&p->vc.lock, flags);
}
static irqreturn_t vd_irq(int irq, void *context)
{
	struct vdma *p = context;
	struct vdesc *desc;
	unsigned long flags;
	u64 status = readq(p->regs + VD_STATUS);

	if (!(status & VD_DONE) || status & VD_BUSY)
		return IRQ_NONE;
	spin_lock_irqsave(&p->vc.lock, flags);
	writeq(2, p->regs + VD_CONTROL); /* legal only once hardware is drained */
	p->interrupts++;
	desc = p->active;
	p->active = NULL;
	if (!desc) {
		p->faulted = true;
		dev_err_ratelimited(p->dev, "unexpected completion; reset required\n");
	} else {
		dma_rmb();
		if (status & VD_ERROR) {
			p->failed_cookie = desc->vd.tx.cookie;
			desc->vd.tx_result.result = DMA_TRANS_WRITE_FAILED;
			desc->vd.tx_result.residue = desc->length;
		}
		p->completed++;
		vchan_cookie_complete(&desc->vd);
		vd_start(p);
	}
	spin_unlock_irqrestore(&p->vc.lock, flags);
	return IRQ_HANDLED;
}
static enum dma_status vd_status(struct dma_chan *chan, dma_cookie_t cookie, struct dma_tx_state *state)
{
	struct vdma *p = vd_chan(chan);
	struct virt_dma_desc *vd;
	enum dma_status status;
	unsigned long flags;

	spin_lock_irqsave(&p->vc.lock, flags);
	status = dma_cookie_status(chan, cookie, state);
	if (cookie == p->failed_cookie || p->faulted)
		status = DMA_ERROR;
	if (status == DMA_IN_PROGRESS) {
		vd = vchan_find_desc(&p->vc, cookie);
		dma_set_residue(state, p->active && p->active->vd.tx.cookie == cookie ?
			p->active->length : vd ? vd_desc(vd)->length : 0);
	}
	spin_unlock_irqrestore(&p->vc.lock, flags);
	return status;
}
static int vd_terminate(struct dma_chan *chan)
{
	struct vdma *p = vd_chan(chan);
	unsigned long flags;
	LIST_HEAD(head);

	spin_lock_irqsave(&p->vc.lock, flags);
	if (p->active || readq(p->regs + VD_STATUS) & VD_BUSY) {
		spin_unlock_irqrestore(&p->vc.lock, flags);
		return -EBUSY; /* hardware has no abort: never pretend it stopped */
	}
	vchan_get_all_descriptors(&p->vc, &head);
	spin_unlock_irqrestore(&p->vc.lock, flags);
	vchan_dma_desc_free_list(&p->vc, &head);
	return 0;
}
static void vd_resources_free(struct dma_chan *chan)
{
	struct vdma *p = vd_chan(chan);

	if (vd_terminate(chan)) {
		dev_err(p->dev, "active channel cannot be freed; reset required\n");
		return;
	}
	vchan_synchronize(&p->vc);
}
static void vd_sync(struct dma_chan *chan) { vchan_synchronize(&vd_chan(chan)->vc); }

static ssize_t dma_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct vdma *p = dev_get_drvdata(dev);

	return sysfs_emit(buf, "status=%#llx interrupts=%llu completed=%llu faulted=%u address_base=%#llx address_bytes=%#llx credits=4 alignment=8 abort=0\n",
		readq(p->regs + VD_STATUS), READ_ONCE(p->interrupts), READ_ONCE(p->completed),
		READ_ONCE(p->faulted), p->base, p->bytes);
}
static DEVICE_ATTR_RO(dma_status);
static struct attribute *vd_attrs[] = { &dev_attr_dma_status.attr, NULL };
static const struct attribute_group vd_group = { .attrs = vd_attrs };

static int vd_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct vdma *p;
	int irq, ret;

	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->dev = dev;
	if (!of_dma_is_coherent(dev->of_node) ||
	    of_property_read_u64(dev->of_node, "openion,ram-base", &p->base) ||
	    of_property_read_u64(dev->of_node, "openion,ram-bytes", &p->bytes) ||
	    !p->bytes || p->bytes > 0x80000000ULL || p->base != 0x80200000ULL)
		return -EINVAL;
	p->regs = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(p->regs))
		return PTR_ERR(p->regs);
	if (readq(p->regs + VD_STATUS) & VD_BUSY)
		return -EBUSY;
	writeq(2, p->regs + VD_CONTROL);
	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(64));
	if (ret)
		return ret;
	irq = platform_get_irq(pdev, 0);
	if (irq < 0)
		return irq;
	dma_cap_set(DMA_MEMCPY, p->dma.cap_mask);
	p->dma.dev = dev;
	p->dma.copy_align = 3;
	p->dma.residue_granularity = DMA_RESIDUE_GRANULARITY_DESCRIPTOR;
	p->dma.device_prep_dma_memcpy = vd_prep;
	p->dma.device_issue_pending = vd_issue;
	p->dma.device_tx_status = vd_status;
	p->dma.device_terminate_all = vd_terminate;
	p->dma.device_free_chan_resources = vd_resources_free;
	p->dma.device_synchronize = vd_sync;
	INIT_LIST_HEAD(&p->dma.channels);
	p->vc.desc_free = vd_free;
	vchan_init(&p->vc, &p->dma);
	ret = devm_request_irq(dev, irq, vd_irq, 0, "valence-dma", p);
	if (ret)
		goto kill_task;
	ret = dma_async_device_register(&p->dma);
	if (ret)
		goto kill_task;
	ret = of_dma_controller_register(dev->of_node, of_dma_xlate_by_chan_id, &p->dma);
	if (ret)
		goto unregister_dma;
	platform_set_drvdata(pdev, p);
	ret = devm_device_add_group(dev, &vd_group);
	if (ret) {
		of_dma_controller_free(dev->of_node);
		goto unregister_dma;
	}
	dev_info(dev, "memcpy DMAengine, IRQ %d, four credits, 64-bit addresses; no abort\n", irq);
	return 0;
unregister_dma:
	dma_async_device_unregister(&p->dma);
kill_task:
	tasklet_kill(&p->vc.task);
	return ret;
}

struct vbench {
	struct device *dev;
	struct mutex lock;
	struct completion done;
	struct dma_chan *chan;
	void *source, *destination;
	dma_addr_t src_dma, dst_dma;
	u64 ns, bytes, rate, finished;
	size_t allocation;
	unsigned int iterations;
	enum dmaengine_tx_result result;
	bool faulted;
};

static void vb_done(void *context, const struct dmaengine_result *result)
{
	struct vbench *p = context;

	p->finished = ktime_get_ns();
	p->result = result->result;
	complete(&p->done);
}
static ssize_t benchmark_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct vbench *p = dev_get_drvdata(dev);
	ssize_t n;

	mutex_lock(&p->lock);
	n = sysfs_emit(buf, "bytes=%llu iterations=%u elapsed_ns=%llu payload_bytes_per_sec=%llu logical_rw_bytes_per_sec=%llu verified=%u faulted=%u timing=dmaengine_submit_to_callback\n",
		p->bytes, p->iterations, p->ns, p->rate, p->rate * 2,
		!!p->rate && !p->faulted, p->faulted);
	mutex_unlock(&p->lock);
	return n;
}
static ssize_t benchmark_store(struct device *dev, struct device_attribute *attr, const char *buf, size_t count)
{
	struct vbench *p = dev_get_drvdata(dev);
	struct device *dma_dev;
	unsigned int bytes, iterations, i;
	char extra;
	int ret = 0;

	if (sscanf(buf, "%u %u %c", &bytes, &iterations, &extra) != 2 ||
	    bytes < 8 || bytes > 8 * 1024 * 1024 || bytes & 7 || !iterations || iterations > 64)
		return -EINVAL;
	if (!mutex_trylock(&p->lock))
		return -EBUSY;
	if (p->faulted) {
		ret = -EIO;
		goto unlock;
	}
	p->rate = 0;
	p->ns = 0;
	p->bytes = bytes;
	p->iterations = iterations;
	p->chan = dma_request_chan(dev, "copy");
	if (IS_ERR(p->chan)) {
		ret = PTR_ERR(p->chan);
		p->chan = NULL;
		goto unlock;
	}
	dma_dev = dmaengine_get_dma_device(p->chan);
	p->allocation = bytes;
	p->source = dma_alloc_coherent(dma_dev, bytes, &p->src_dma, GFP_KERNEL);
	p->destination = dma_alloc_coherent(dma_dev, bytes, &p->dst_dma, GFP_KERNEL);
	if (!p->source || !p->destination) {
		ret = -ENOMEM;
		goto free_buffers;
	}
	for (i = 0; i < iterations; i++) {
		struct dma_async_tx_descriptor *tx;
		dma_cookie_t cookie;
		u64 started;

		memset(p->source, 0xa5 ^ i, bytes);
		memset(p->destination, 0x5a ^ i, bytes);
		dma_wmb();
		reinit_completion(&p->done);
		tx = dmaengine_prep_dma_memcpy(p->chan, p->dst_dma, p->src_dma, bytes,
					      DMA_PREP_INTERRUPT | DMA_CTRL_ACK);
		if (!tx) {
			ret = -EINVAL;
			goto free_buffers;
		}
		tx->callback_result = vb_done;
		tx->callback_param = p; /* persistent, including after timeout */
		started = ktime_get_ns();
		cookie = dmaengine_submit(tx);
		if (dma_submit_error(cookie)) {
			ret = dma_submit_error(cookie);
			goto free_buffers;
		}
		dma_async_issue_pending(p->chan);
		if (!wait_for_completion_timeout(&p->done, msecs_to_jiffies(10000))) {
			ret = -ETIMEDOUT;
			if (dmaengine_terminate_sync(p->chan)) {
				p->faulted = true;
				dev_err(dev, "timeout: active DMA/channel/buffers pinned; RESET REQUIRED\n");
				goto unlock;
			}
			goto free_buffers;
		}
		p->ns += p->finished - started;
		dma_rmb();
		if (p->result != DMA_TRANS_NOERROR || memcmp(p->source, p->destination, bytes)) {
			ret = -EIO;
			goto free_buffers;
		}
		cond_resched();
	}
	if (p->ns)
		p->rate = div64_u64((u64)bytes * iterations * NSEC_PER_SEC, p->ns);
	dev_info(dev, "DMA memcpy PASS %u x %u bytes, %llu payload B/s; CPU fill/verify excluded\n",
		 iterations, bytes, p->rate);
free_buffers:
	dmaengine_synchronize(p->chan);
	if (p->source)
		dma_free_coherent(dma_dev, p->allocation, p->source, p->src_dma);
	if (p->destination)
		dma_free_coherent(dma_dev, p->allocation, p->destination, p->dst_dma);
	p->source = p->destination = NULL;
	dma_release_channel(p->chan);
	p->chan = NULL;
unlock:
	mutex_unlock(&p->lock);
	return ret ? ret : count;
}
static DEVICE_ATTR_RW(benchmark);
static struct attribute *vb_attrs[] = { &dev_attr_benchmark.attr, NULL };
static const struct attribute_group vb_group = { .attrs = vb_attrs };

static int vb_probe(struct platform_device *pdev)
{
	struct vbench *p = devm_kzalloc(&pdev->dev, sizeof(*p), GFP_KERNEL);

	if (!p)
		return -ENOMEM;
	p->dev = &pdev->dev;
	mutex_init(&p->lock);
	init_completion(&p->done);
	platform_set_drvdata(pdev, p);
	return devm_device_add_group(&pdev->dev, &vb_group);
}
static const struct of_device_id vd_of_match[] = {
	{ .compatible = "openion,valence-memcpy-dma-v1" }, {}
};
static const struct of_device_id vb_of_match[] = {
	{ .compatible = "openion,valence-dma-bench-v1" }, {}
};
MODULE_DEVICE_TABLE(of, vd_of_match);
MODULE_DEVICE_TABLE(of, vb_of_match);
static struct platform_driver vd_driver = {
	.probe = vd_probe,
	.driver = { .name = "valence-dma", .of_match_table = vd_of_match, .suppress_bind_attrs = true },
};
static struct platform_driver vb_driver = {
	.probe = vb_probe,
	.driver = { .name = "valence-dma-bench", .of_match_table = vb_of_match, .suppress_bind_attrs = true },
};
static int __init vd_init(void)
{
	int ret = platform_driver_register(&vd_driver);

	if (ret)
		return ret;
	ret = platform_driver_register(&vb_driver);
	if (ret)
		platform_driver_unregister(&vd_driver);
	return ret;
}
module_init(vd_init);
MODULE_LICENSE("GPL");
MODULE_AUTHOR(VALENCE_VENDOR);
MODULE_DESCRIPTION("Valence VL100 aligned memcpy DMAengine and explicit bandwidth client");
MODULE_VERSION(VALENCE_DRIVER_VERSION);
