// SPDX-License-Identifier: GPL-2.0-only
/* VL100 fixed-rate clock provider. Only proven leaf domains may be gated.
 * No frequency scaling, CPU/DDR gating, hot reset, or unsolicited CMU IRQs.
 */
#define pr_fmt(fmt) "valence-cmu: " fmt
#include <linux/clk-provider.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include "valence_driver_names.h"

#define VC_ID 0x56434d5500010001ULL
#define VC_STOP 0x20
#define VC_STOPPED 0x30
#define VC_ISOLATED 0x40
#define VC_ADMISSION 0x48
#define VC_WAKE 0x50
#define VC_WAKE_SET 0x60
#define VC_FAULT 0x68

struct vcmu;
struct vclock {
	struct clk_hw hw;
	struct vcmu *cmu;
	unsigned long rate;
	unsigned int index;
	bool gateable;
};
struct vcmu {
	struct device *dev;
	void __iomem *regs;
	struct mutex lock;
	struct clk_hw_onecell_data *data;
	u64 present, gateable;
};

static struct vclock *vclock_of(struct clk_hw *hw)
{
	return container_of(hw, struct vclock, hw);
}

static unsigned long vc_rate(struct clk_hw *hw, unsigned long parent_rate)
{
	return vclock_of(hw)->rate;
}

static int vc_prepare(struct clk_hw *hw)
{
	struct vclock *clock = vclock_of(hw);
	struct vcmu *p = clock->cmu;
	u64 bit = BIT_ULL(clock->index), value;
	int ret;

	if (!clock->gateable)
		return 0;
	mutex_lock(&p->lock);
	writeq(readq(p->regs + VC_STOP) & ~bit, p->regs + VC_STOP);
	writeq(bit, p->regs + VC_WAKE_SET);
	ret = readq_poll_timeout(p->regs + VC_ADMISSION, value, value & bit, 20, 20000);
	if (!ret && (readq(p->regs + VC_ISOLATED) & bit))
		ret = -EIO;
	if (!ret)
		writeq(bit, p->regs + VC_WAKE);
	else
		dev_err(p->dev, "clock %u resume failed: %d\n", clock->index, ret);
	mutex_unlock(&p->lock);
	return ret;
}

static void vc_unprepare(struct clk_hw *hw)
{
	struct vclock *clock = vclock_of(hw);
	struct vcmu *p = clock->cmu;
	u64 bit = BIT_ULL(clock->index), value;
	int ret;

	if (!clock->gateable)
		return;
	mutex_lock(&p->lock);
	/* Latched wake takes precedence over STOP. Clear only this leaf's event. */
	writeq(bit, p->regs + VC_WAKE);
	writeq(readq(p->regs + VC_STOP) | bit, p->regs + VC_STOP);
	ret = readq_poll_timeout(p->regs + VC_STOPPED, value, value & bit, 20, 20000);
	if (ret) {
		writeq(readq(p->regs + VC_STOP) & ~bit, p->regs + VC_STOP);
		writeq(bit, p->regs + VC_WAKE_SET);
		dev_warn(p->dev, "clock %u stop refused; restored running request\n", clock->index);
	}
	mutex_unlock(&p->lock);
}

static int vc_is_prepared(struct clk_hw *hw)
{
	struct vclock *clock = vclock_of(hw);

	return !!(readq(clock->cmu->regs + VC_ADMISSION) & BIT_ULL(clock->index));
}

static const struct clk_ops vc_ops = {
	.prepare = vc_prepare, .unprepare = vc_unprepare,
	.is_prepared = vc_is_prepared, .recalc_rate = vc_rate,
};

static ssize_t clock_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct vcmu *p = dev_get_drvdata(dev);

	return sysfs_emit(buf, "present=%#llx gateable=%#llx enabled=%#llx stopped=%#llx admission=%#llx isolated=%#llx faults=%#llx fixed_rate=1\n",
		p->present, p->gateable, readq(p->regs + 0x28), readq(p->regs + VC_STOPPED),
		readq(p->regs + VC_ADMISSION), readq(p->regs + VC_ISOLATED), readq(p->regs + VC_FAULT));
}
static DEVICE_ATTR_RO(clock_status);
static struct attribute *vc_attrs[] = { &dev_attr_clock_status.attr, NULL };
static const struct attribute_group vc_group = { .attrs = vc_attrs };

static int vc_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct vcmu *p;
	unsigned int count, i;
	int ret;

	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->dev = dev;
	mutex_init(&p->lock);
	p->regs = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(p->regs))
		return PTR_ERR(p->regs);
	if (readq(p->regs) != VC_ID)
		return -ENODEV;
	count = (readq(p->regs + 8) >> 16) & 0xffff;
	p->present = readq(p->regs + 0x10);
	p->gateable = readq(p->regs + 0x18);
	if (!count || count > 16 || p->present >> count ||
	    p->gateable & ~p->present || p->gateable & ~0x68ULL)
		return -EINVAL;
	/* BootROM leaves resources running. Do not enable wake IRQs here:
	 * a persistent GMAC RX wake would otherwise flood the IRQ adapter. */
	writeq(0, p->regs + 0x70);
	p->data = devm_kzalloc(dev, struct_size(p->data, hws, count), GFP_KERNEL);
	if (!p->data)
		return -ENOMEM;
	p->data->num = count;
	for (i = 0; i < count; i++) {
		struct clk_init_data init = {};
		struct vclock *clock;
		u64 parent = readq(p->regs + 0x120 + i * 0x40);
		const struct clk_hw *parent_hw;

		if (!(p->present & BIT_ULL(i))) {
			p->data->hws[i] = ERR_PTR(-ENOENT);
			continue;
		}
		if (readq(p->regs + 0x100 + i * 0x40) != i ||
		    (parent != U64_MAX && (parent >= i || !(p->present & BIT_ULL(parent)))))
			return -EINVAL;
		clock = devm_kzalloc(dev, sizeof(*clock), GFP_KERNEL);
		if (!clock)
			return -ENOMEM;
		clock->cmu = p;
		clock->index = i;
		clock->gateable = !!(p->gateable & BIT_ULL(i));
		clock->rate = readq(p->regs + 0x108 + i * 0x40);
		if (!clock->rate)
			return -EINVAL;
		init.name = devm_kasprintf(dev, GFP_KERNEL, "valence-cmu-%u", i);
		if (!init.name)
			return -ENOMEM;
		init.ops = &vc_ops;
		/* Keep console UART and ungateable root clocks alive. */
		init.flags = (!clock->gateable || i == 3) ? CLK_IS_CRITICAL : 0;
		if (parent != U64_MAX) {
			parent_hw = p->data->hws[parent];
			init.parent_hws = &parent_hw;
			init.num_parents = 1;
		}
		clock->hw.init = &init;
		ret = devm_clk_hw_register(dev, &clock->hw);
		if (ret)
			return ret;
		p->data->hws[i] = &clock->hw;
	}
	ret = devm_of_clk_add_hw_provider(dev, of_clk_hw_onecell_get, p->data);
	if (ret)
		return ret;
	platform_set_drvdata(pdev, p);
	ret = devm_device_add_group(dev, &vc_group);
	if (ret)
		return ret;
	dev_info(dev, "%u fixed-rate resources, gateable=%#llx; UART critical\n", count, p->gateable);
	return 0;
}

static const struct of_device_id vc_of_match[] = {
	{ .compatible = "openion,valence-cmu-v1" }, {}
};
MODULE_DEVICE_TABLE(of, vc_of_match);
static struct platform_driver vc_driver = {
	.probe = vc_probe,
	.driver = { .name = "valence-cmu", .of_match_table = vc_of_match, .suppress_bind_attrs = true },
};
static int __init vc_init(void) { return platform_driver_register(&vc_driver); }
module_init(vc_init);
MODULE_LICENSE("GPL");
MODULE_AUTHOR(VALENCE_VENDOR);
MODULE_DESCRIPTION("Valence VL100 fixed-rate leaf clock manager");
MODULE_VERSION(VALENCE_DRIVER_VERSION);
