// SPDX-License-Identifier: GPL-2.0-only
/* CMU rate ABI2 + telemetry ABI1, read-only. No cpufreq policy or clock writes. */
#include <linux/io.h>
#include <linux/clk-provider.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include "valence_clockmon_abi.h"
#include "valence_driver_names.h"

struct valence_clockmon {
	void __iomem *rate, *perf;
	struct mutex lock;
	struct clk_hw_onecell_data *clocks;
};
struct vcm_clock {
	struct clk_hw hw;
	struct valence_clockmon *monitor;
	unsigned int domain;
};

static u64 vcm_read(void *ctx, unsigned int offset)
{
	struct valence_clockmon *p = ctx;
	return offset < 0x100 ? readq(p->rate + offset) : readq(p->perf + offset - 0x100);
}

static unsigned long vcm_recalc_rate(struct clk_hw *hw, unsigned long parent_rate)
{
	struct vcm_clock *clock = container_of(hw, struct vcm_clock, hw);
	return (unsigned long)vcm_current_rate(vcm_read, clock->monitor, clock->domain);
}
static const struct clk_ops vcm_clock_ops = { .recalc_rate = vcm_recalc_rate };

static int vcm_register_clocks(struct device *dev, struct valence_clockmon *p)
{
	unsigned int d;
	p->clocks = devm_kzalloc(dev, struct_size(p->clocks, hws, 2), GFP_KERNEL);
	if (!p->clocks)
		return -ENOMEM;
	p->clocks->num = 2;
	for (d = 0; d < 2; d++) {
		struct clk_init_data init = {};
		struct vcm_clock *clock = devm_kzalloc(dev, sizeof(*clock), GFP_KERNEL);
		int ret;
		if (!clock)
			return -ENOMEM;
		init.name = d ? "valence-applied-fabric" : "valence-applied-cpu";
		init.ops = &vcm_clock_ops;
		init.flags = CLK_GET_RATE_NOCACHE | CLK_IS_CRITICAL;
		clock->monitor = p; clock->domain = d; clock->hw.init = &init;
		ret = devm_clk_hw_register(dev, &clock->hw);
		if (ret)
			return ret;
		p->clocks->hws[d] = &clock->hw;
	}
	/* No parent clocks: clockmon must never depend back on CMUv1. */
	return devm_of_clk_add_hw_provider(dev, of_clk_hw_onecell_get, p->clocks);
}

static ssize_t dvfs_policy_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "runtime_switching=disabled access=read-only boot_change=none qualification=not-inferred\n");
}
static DEVICE_ATTR_RO(dvfs_policy);

static ssize_t rate_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct valence_clockmon *p = dev_get_drvdata(dev);
	struct vcm_rate rate[2];
	unsigned int d;
	int ret;
	ssize_t len = 0;
	mutex_lock(&p->lock);
	ret = vcm_validate(vcm_read, p);
	for (d = 0; !ret && d < 2; d++)
		ret = vcm_read_rate(vcm_read, p, d, &rate[d], 4);
	mutex_unlock(&p->lock);
	if (ret)
		return ret;
	for (d = 0; d < 2; d++) {
		u64 *r = rate[d].word;
		len += sysfs_emit_at(buf, len,
			"%s configured_hz=%llu requested_hz=%llu target_hz=%llu boot_hz=%llu status=%#llx errors=%#llx staged_mdo=%#llx caps=%#llx admission=%#llx completed=%llu state=%llu min_hz=%llu max_hz=%llu reference_hz=%llu stable_live_read=1\n",
			d ? "fabric" : "cpu", r[1], r[0], r[4], r[5], r[2], r[3], r[6],
			r[7], r[8], r[10], r[11], r[13], r[12], r[14]);
	}
	return len;
}
static DEVICE_ATTR_RO(rate_status);

static ssize_t snapshot_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct valence_clockmon *p = dev_get_drvdata(dev);
	struct vcm_snapshot snapshot;
	unsigned int d, i;
	int ret;
	ssize_t len = 0;
	mutex_lock(&p->lock);
	ret = vcm_read_snapshot(vcm_read, p, &snapshot, 4);
	mutex_unlock(&p->lock);
	if (ret)
		return ret;
	for (d = 0; d < 2; d++) {
		struct vcm_meter *s = &snapshot.domain[d];
		len += sysfs_emit_at(buf, len,
			"%s sequence=%llu flags=%#llx valid=%u counter_bits=%u reference_hz=%llu window=%llu timestamp=%llu ",
			d ? "fabric" : "cpu", s->sequence, s->flags, vcm_meter_valid(s),
			s->width, s->reference_hz, s->window, s->timestamp);
		if (vcm_meter_valid(s))
			len += sysfs_emit_at(buf, len, "measured_hz=%llu", vcm_measured_hz(s));
		else
			len += sysfs_emit_at(buf, len, "measured_hz=unavailable");
		for (i = 0; i < 8; i++)
			len += sysfs_emit_at(buf, len, " delta%u=%u total%u=%u", i, s->delta[i], i, s->total[i]);
		len += sysfs_emit_at(buf, len, "\n");
	}
	return len;
}
static DEVICE_ATTR_RO(snapshot);

static struct attribute *vcm_attrs[] = {
	&dev_attr_dvfs_policy.attr, &dev_attr_rate_status.attr, &dev_attr_snapshot.attr, NULL,
};
static const struct attribute_group vcm_group = { .attrs = vcm_attrs };

static int vcm_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct valence_clockmon *p;
	struct resource *rate, *perf;
	int ret;
	rate = platform_get_resource_byname(pdev, IORESOURCE_MEM, "rate");
	perf = platform_get_resource_byname(pdev, IORESOURCE_MEM, "perf");
	if (!rate || !perf || rate->start != 0x10080800 || resource_size(rate) != 0x100 ||
	    perf->start != 0x10080900 || resource_size(perf) != 0x200)
		return -EINVAL;
	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->rate = devm_ioremap_resource(dev, rate);
	if (IS_ERR(p->rate))
		return PTR_ERR(p->rate);
	p->perf = devm_ioremap_resource(dev, perf);
	if (IS_ERR(p->perf))
		return PTR_ERR(p->perf);
	mutex_init(&p->lock);
	ret = vcm_validate(vcm_read, p);
	if (ret)
		return dev_err_probe(dev, ret, "unsupported CMU/telemetry ABI or clock contract\n");
	platform_set_drvdata(pdev, p);
	ret = vcm_register_clocks(dev, p);
	if (ret)
		return ret;
	ret = devm_device_add_group(dev, &vcm_group);
	if (ret)
		return ret;
	dev_info(dev, "rate ABI2 / meter ABI1 read-only; no runtime DVFS or boot-rate change\n");
	return 0;
}
static const struct of_device_id vcm_match[] = {
	{ .compatible = "openion,valence-clock-monitor-v1" }, {},
};
MODULE_DEVICE_TABLE(of, vcm_match);
static struct platform_driver vcm_driver = {
	.probe = vcm_probe,
	.driver = { .name = "valence-clockmon", .of_match_table = vcm_match,
		.suppress_bind_attrs = true },
};
module_platform_driver(vcm_driver);
MODULE_LICENSE("GPL");
MODULE_AUTHOR(VALENCE_VENDOR);
MODULE_DESCRIPTION("Valence read-only CMU rate and coherent performance telemetry");
MODULE_VERSION(VALENCE_DRIVER_VERSION);
