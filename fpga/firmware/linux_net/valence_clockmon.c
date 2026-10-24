// SPDX-License-Identifier: GPL-2.0-only
/* CMU rate ABI2 + CPU telemetry ABI1/2, fabric ABI1. Default read-only; CPU opt-in and separate
 * boot-only I1 pair opt-in. Never runtime fabric scaling. */
#include <linux/io.h>
#include <linux/capability.h>
#include <linux/delay.h>
#include <linux/ktime.h>
#include <linux/math64.h>
#include <linux/clk-provider.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include "valence_clockmon_abi.h"
#include "valence_cpu_rate_transaction.h"
#include "valence_driver_names.h"

struct valence_clockmon {
	void __iomem *rate, *perf;
	struct mutex lock;
	struct clk_hw_onecell_data *clocks;
	bool cpu_control, cpu_armed, cpu_starting;
	bool fabric_boot_enabled, fabric_attempted, rate_fault;
	u32 cpu_boot_hz, fabric_boot_hz;
	unsigned int cpu_lanes;
	int cpu_last_result, cpu_control_error, fabric_last_result;
	struct vcpu_transaction cpu_transaction, fabric_transaction;
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
	/* A failed shared epoch cannot be followed by another software write. */
	if (clock->domain && READ_ONCE(clock->monitor->fabric_boot_enabled) &&
	    READ_ONCE(clock->monitor->fabric_transaction.poisoned) &&
	    !READ_ONCE(clock->monitor->fabric_transaction.actual_hz))
		return 0;
	/* A poisoned uncertain result is not a cached current frequency. */
	if (!clock->domain && READ_ONCE(clock->monitor->cpu_control) &&
	    READ_ONCE(clock->monitor->cpu_transaction.poisoned) &&
	    !READ_ONCE(clock->monitor->cpu_transaction.actual_hz))
		return 0;
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


/* Runtime CPU writer. The separate fabric adapter is boot-only. Neither
 * adapter permits W1C, gate or raw DRP writes. */
static void vcm_cpu_write(void *ctx, unsigned int off, u64 value)
{
	struct valence_clockmon *p = ctx;
	if (WARN_ON(off != 0 && off != 0x30))
		return;
	writeq(value, p->rate + off);
}
static void vcm_cpu_pause(void *ctx)
{
	usleep_range(50, 100);
}
static u64 vcm_cpu_now_us(void *ctx)
{
	return div_u64(ktime_get_ns(), 1000);
}
/* Only this boot-only adapter can address the fabric ABI2 page. It is not
 * exported through sysfs and never writes CMUv1 (index2 there is fixed TIME). */
static u64 vcm_fabric_read(void *ctx, unsigned int off)
{
	if (WARN_ON(off >= 0x80))
		return 0;
	return vcm_read(ctx, off + 0x80);
}
static void vcm_fabric_write(void *ctx, unsigned int off, u64 value)
{
	struct valence_clockmon *p = ctx;
	if (WARN_ON(!p->cpu_starting || !p->fabric_boot_enabled ||
	    !p->fabric_attempted || (off != 0 && off != 0x30)))
		return;
	writeq(value, p->rate + 0x80 + off);
}
static int vcm_fabric_owned_locked(struct valence_clockmon *p)
{
	const struct vcpu_io io = { p, vcm_fabric_read, vcm_fabric_write,
		vcm_cpu_pause, vcm_cpu_now_us };
	u32 completed;
	lockdep_assert_held(&p->lock);
	if (!p->fabric_transaction.initialized || p->fabric_transaction.poisoned ||
	    !vcpu_contract_limit(&io, 250000000) ||
	    vcpu_observe(&io, &p->fabric_transaction, &completed) ||
	    !p->fabric_transaction.actual_hz || p->fabric_transaction.errors ||
	    vcm_fabric_read(p, 0x58) || completed != p->fabric_transaction.last_completion ||
	    p->fabric_transaction.known_parameters != vcpu_parameters(p->fabric_transaction.actual_hz)) {
		p->fabric_transaction.actual_hz = 0;
		p->fabric_transaction.poisoned = 1;
		p->rate_fault = true;
		return -EIO;
	}
	return 0;
}
static int vcm_fabric_boot_locked(struct valence_clockmon *p)
{
	const struct vcpu_io cpu = { p, vcm_read, vcm_cpu_write, vcm_cpu_pause, vcm_cpu_now_us };
	const struct vcpu_io fabric = { p, vcm_fabric_read, vcm_fabric_write,
		vcm_cpu_pause, vcm_cpu_now_us };
	u32 completed;
	int ret;
	lockdep_assert_held(&p->lock);
	if (!p->cpu_starting || !p->fabric_boot_enabled || p->fabric_attempted || p->rate_fault)
		return -EPERM;
	/* A failed CPU request never authorizes a fabric transaction. Observe its
	 * untouched real50 result for userspace, without fabric writes or retry. */
	ret = vcm_fabric_owned_locked(p);
	if (ret || p->cpu_last_result || p->cpu_transaction.poisoned) {
		p->fabric_last_result = ret ? ret : -ECANCELED;
		return p->fabric_last_result;
	}
	if (vcpu_observe(&cpu, &p->cpu_transaction, &completed) ||
	    p->cpu_transaction.actual_hz != 125000000 || p->cpu_transaction.errors ||
	    completed != p->cpu_transaction.last_completion ||
	    p->cpu_transaction.known_parameters != 0x08280a || vcm_read(p, 0x58)) {
		p->cpu_transaction.actual_hz = 0;
		p->cpu_transaction.poisoned = 1; p->rate_fault = true;
		p->fabric_last_result = -EIO;
		return -EIO;
	}
	p->fabric_attempted = true; /* Irrevocable before either MMIO write. */
	ret = vcpu_set_limit(&fabric, &p->fabric_transaction, 125000000, 2000, 250000000);
	p->fabric_last_result = ret;
	if (ret)
		p->rate_fault = true; /* Includes confirmed fallback: no shared-owner retry. */
	return ret;
}

static int vcm_cpu_set_locked(struct valence_clockmon *p, u32 hz)
{
	const struct vcpu_io io = { p, vcm_read, vcm_cpu_write, vcm_cpu_pause, vcm_cpu_now_us };
	lockdep_assert_held(&p->lock);
	if (!p->cpu_control || !p->cpu_armed)
		return -EPERM;
	if (!vcpu_parameters(hz))
		return -EINVAL;
	if (p->rate_fault || vcm_fabric_owned_locked(p))
		return -EIO;
	/* 50/125 was NOT physically qualified. No hidden fabric-down request. */
	if (hz == 50000000 && p->fabric_transaction.actual_hz != 50000000)
		return -EPERM;
	p->cpu_last_result = vcpu_set(&io, &p->cpu_transaction, hz, 2000);
	return p->cpu_last_result;
}

static ssize_t cpu_control_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct valence_clockmon *p = dev_get_drvdata(dev);
	ssize_t n;
	mutex_lock(&p->lock);
	n = sysfs_emit(buf, "enabled=%u armed=%u poisoned=%u disabled_reason=%d last_result=%d requested_hz=%u last_confirmed_hz=%u status=%#llx errors=%#llx boot_target_hz=%u shared_fault=%u runtime_fabric_control=disabled qualification=linux-load-unverified\n",
		p->cpu_control, p->cpu_armed, p->cpu_transaction.poisoned,
		p->cpu_control_error, p->cpu_last_result, p->cpu_transaction.requested_hz,
		p->cpu_transaction.actual_hz, p->cpu_transaction.status,
		p->cpu_transaction.errors, p->cpu_boot_hz, p->rate_fault);
	mutex_unlock(&p->lock);
	return n;
}
static DEVICE_ATTR_RO(cpu_control);

static ssize_t cpu_arm_store(struct device *dev, struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct valence_clockmon *p = dev_get_drvdata(dev);
	unsigned int value;
	int ret;
	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;
	ret = kstrtouint(buf, 0, &value);
	if (ret || value != 1)
		return -EINVAL;
	mutex_lock(&p->lock);
	ret = p->cpu_starting ? -EAGAIN : !p->cpu_control ? -EOPNOTSUPP :
		(p->cpu_transaction.poisoned || p->rate_fault) ? -EIO : 0;
	if (!ret)
		p->cpu_armed = true; /* Arm alone never submits a request. */
	mutex_unlock(&p->lock);
	if (ret)
		return ret;
	return count;
}
static DEVICE_ATTR_WO(cpu_arm);

static ssize_t cpu_target_hz_store(struct device *dev, struct device_attribute *attr,
				   const char *buf, size_t count)
{
	struct valence_clockmon *p = dev_get_drvdata(dev);
	u32 hz;
	int ret;
	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;
	ret = kstrtou32(buf, 0, &hz);
	if (ret)
		return ret;
	mutex_lock(&p->lock);
	ret = p->cpu_starting ? -EAGAIN : vcm_cpu_set_locked(p, hz);
	mutex_unlock(&p->lock);
	if (ret)
		return ret;
	return count;
}
static DEVICE_ATTR_WO(cpu_target_hz);

/* Reject DT CPU-clock consumers beyond the existing read-only CMU alias.
 * Runtime overlays and module unloading are forbidden by the control contract.
 * This does not make arbitrary future modules/notifiers supported. */
static int vcm_cpu_observer_topology(struct device_node *monitor)
{
	struct device_node *node;
	for_each_node_with_property(node, "clocks") {
		int count, i;
		if (!of_device_is_available(node) || !of_find_property(node, "clocks", NULL))
			continue;
		count = of_count_phandle_with_args(node, "clocks", "#clock-cells");
		if (count < 0) {
			of_node_put(node);
			return -EINVAL;
		}
		for (i = 0; i < count; i++) {
			struct of_phandle_args args;
			bool forbidden = false;
			if (of_parse_phandle_with_args(node, "clocks", "#clock-cells", i, &args)) {
				of_node_put(node);
				return -EINVAL;
			}
			if (args.np == monitor && args.args_count == 1 && args.args[0] == 0)
				forbidden = !of_device_is_compatible(node, "openion,valence-cmu-v1") ||
					count != 1 || of_property_match_string(node, "clock-names", "cpu-rate") != 0;
			if (of_device_is_compatible(args.np, "openion,valence-cmu-v1") &&
			    args.args_count == 1 && args.args[0] == 1)
				forbidden = true;
			if (args.np == monitor && args.args_count == 1 && args.args[0] == 1)
				forbidden = true;
			of_node_put(args.np);
			if (forbidden) {
				of_node_put(node);
				return -EOPNOTSUPP;
			}
		}
	}
	return 0;
}

/* Closed-image contract, not a generic CCF set_rate provider. The CPU clock
 * is only observed via NOCACHE; fixed TIME/UART/MAC clocks are unchanged. */
static int vcm_cpu_control_config(struct device *dev, struct valence_clockmon *p)
{
	struct device_node *cpu, *cpus;
	u32 timebase;
	bool i1;
	p->cpu_boot_hz = 50000000; p->fabric_boot_hz = 50000000;
	if (!of_property_read_bool(dev->of_node, "openion,cpu-rate-control"))
		return of_find_property(dev->of_node, "openion,fabric-boot-hz", NULL) ||
			of_property_read_bool(dev->of_node, "openion,i1-boot-pair-125") ? -EINVAL : 0;
	if (IS_ENABLED(CONFIG_CPU_FREQ) || IS_ENABLED(CONFIG_SMP) ||
	    IS_ENABLED(CONFIG_SUSPEND) || IS_ENABLED(CONFIG_HIBERNATION) ||
	    IS_ENABLED(CONFIG_CPU_IDLE) || IS_ENABLED(CONFIG_OF_OVERLAY) ||
	    IS_ENABLED(CONFIG_MODULE_UNLOAD) || IS_ENABLED(CONFIG_DEVMEM))
		return -EOPNOTSUPP;
	if (!of_property_read_bool(dev->of_node, "openion,cpu-clock-observer-only"))
		return -EINVAL;
	cpu = of_find_node_by_path("/cpus/cpu@0");
	i1 = cpu && of_device_is_compatible(cpu, "openion,valence-i1");
	of_node_put(cpu);
	cpus = of_find_node_by_path("/cpus");
	if (!cpus)
		return -EINVAL;
	if (of_property_read_u32(cpus, "timebase-frequency", &timebase))
		timebase = 0;
	of_node_put(cpus);
	if (!i1 || timebase != 250000000)
		return -ENODEV;
	if (vcm_cpu_observer_topology(dev->of_node))
		return -EOPNOTSUPP;
	if (of_find_property(dev->of_node, "openion,cpu-boot-hz", NULL) &&
	    of_property_read_u32(dev->of_node, "openion,cpu-boot-hz", &p->cpu_boot_hz))
		return -EINVAL;
	if (!vcpu_parameters(p->cpu_boot_hz))
		return -EINVAL;
	{
		const struct vcpu_io io = { p, vcm_read, vcm_cpu_write, vcm_cpu_pause, vcm_cpu_now_us };
		if (vcpu_initialize(&io, &p->cpu_transaction))
			return -EBUSY;
	}
	{
		const struct vcpu_io io = { p, vcm_fabric_read, vcm_fabric_write,
			vcm_cpu_pause, vcm_cpu_now_us };
		if (vcpu_initialize_limit(&io, &p->fabric_transaction, 250000000))
			return -EBUSY;
	}
	if (of_find_property(dev->of_node, "openion,fabric-boot-hz", NULL) ||
	    of_property_read_bool(dev->of_node, "openion,i1-boot-pair-125")) {
		struct device_node *uart = of_find_node_by_path("/soc/serial@10000000");
		bool uart_disabled = uart && !of_device_is_available(uart);
		of_node_put(uart);
		if (!uart_disabled || p->cpu_boot_hz != 125000000 ||
		    !of_property_read_bool(dev->of_node, "openion,i1-boot-pair-125") ||
		    of_property_read_u32(dev->of_node, "openion,fabric-boot-hz", &p->fabric_boot_hz) ||
		    p->fabric_boot_hz != 125000000)
			return -EINVAL;
		p->fabric_boot_enabled = true;
	}
	p->cpu_control = true;
	return 0;
}

static ssize_t dvfs_policy_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct valence_clockmon *p = dev_get_drvdata(dev);
	return sysfs_emit(buf, "runtime_switching=%s access=%s boot_target_hz=%u runtime_fabric_writes=disabled boot_fabric_target_hz=%u boot_fabric_attempted=%u qualification=not-inferred\n",
		p->rate_fault ? "latched-fault" : p->cpu_control ? "cpu-manual-opt-in" : "disabled",
		p->cpu_control ? "root-only-cpu-50-125" : "read-only", p->cpu_boot_hz,
		p->fabric_boot_hz, p->fabric_attempted);
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
	ret = vcm_validate_profile(vcm_read, p, p->cpu_lanes);
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
	ret = vcm_read_snapshot_profile(vcm_read, p, &snapshot, 4, p->cpu_lanes);
	mutex_unlock(&p->lock);
	if (ret)
		return ret;
	for (d = 0; d < 2; d++) {
		struct vcm_meter *s = &snapshot.domain[d];
		len += sysfs_emit_at(buf, len,
			"%s sequence=%llu flags=%#llx valid=%u counter_bits=%u reference_hz=%llu window=%llu timestamp=%llu ",
			d ? "fabric" : "cpu", s->sequence, s->flags, vcm_meter_valid(s),
			s->width, s->reference_hz, s->window, s->timestamp);
		if (!d)
			len += sysfs_emit_at(buf, len, "retirement_lanes=%u scalar_request_lane=%u ",
				s->retirement_lanes, s->retirement_lanes == 2 ? 0 : 1);
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

static ssize_t fabric_boot_control_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct valence_clockmon *p = dev_get_drvdata(dev);
	ssize_t n;
	mutex_lock(&p->lock);
	n = sysfs_emit(buf, "enabled=%u attempted=%u poisoned=%u last_result=%d last_confirmed_hz=%u boot_target_hz=%u shared_fault=%u runtime_fabric_writes=disabled qualification=linux-load-unverified\n",
		p->fabric_boot_enabled, p->fabric_attempted, p->fabric_transaction.poisoned,
		p->fabric_last_result, p->fabric_transaction.actual_hz, p->fabric_boot_hz, p->rate_fault);
	mutex_unlock(&p->lock);
	return n;
}
static DEVICE_ATTR_RO(fabric_boot_control);

static struct attribute *vcm_attrs[] = {
	&dev_attr_dvfs_policy.attr, &dev_attr_rate_status.attr, &dev_attr_snapshot.attr,
	&dev_attr_cpu_control.attr, &dev_attr_fabric_boot_control.attr, &dev_attr_cpu_arm.attr, &dev_attr_cpu_target_hz.attr, NULL,
};
static const struct attribute_group vcm_group = { .attrs = vcm_attrs };

/* Profile identity is checked before resource mapping or extension MMIO.
 * A1 has no write admission in this driver, including startup properties. */
static int vcm_hardware_profile(struct device *dev)
{
	struct device_node *cpu = of_find_node_by_path("/cpus/cpu@0");
	bool i1 = cpu && of_device_is_compatible(cpu, "openion,valence-i1");
	bool a1 = cpu && of_device_is_compatible(cpu, "openion,orbital-a1");
	bool experimental = of_device_is_compatible(dev->of_node,
		"openion,valence-a1-runtime-clock-monitor-v2");
	of_node_put(cpu);
	if (!experimental)
		return i1 && of_device_is_compatible(dev->of_node,
			"openion,valence-clock-monitor-v1") ? 1 : -ENODEV;
	if (!a1 || i1 || !of_machine_is_compatible("openion,valence-a1-runtime-v2"))
		return -ENODEV;
	if (of_find_property(dev->of_node, "openion,cpu-rate-control", NULL) ||
	    of_find_property(dev->of_node, "openion,cpu-clock-observer-only", NULL) ||
	    of_find_property(dev->of_node, "openion,cpu-boot-hz", NULL) ||
	    of_find_property(dev->of_node, "openion,fabric-boot-hz", NULL) ||
	    of_find_property(dev->of_node, "openion,i1-boot-pair-125", NULL))
		return -EINVAL;
	return 2;
}

static int vcm_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct valence_clockmon *p;
	struct resource *rate, *perf;
	int ret, profile = vcm_hardware_profile(dev);
	if (profile < 0)
		return profile;
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
	p->cpu_lanes = profile;
	p->cpu_boot_hz = 50000000; p->fabric_boot_hz = 50000000;
	ret = vcm_validate_profile(vcm_read, p, p->cpu_lanes);
	if (ret)
		return dev_err_probe(dev, ret, "unsupported CMU/telemetry ABI or clock contract\n");
	ret = profile == 1 ? vcm_cpu_control_config(dev, p) : 0;
	if (ret) {
		/* Failed write admission must not remove the read-only clock parent
		 * or strand CMU consumers in deferred probe. Never infer a tuple. */
		p->cpu_control = false;
		p->cpu_control_error = ret; p->cpu_last_result = ret; p->fabric_last_result = ret;
		p->cpu_transaction.poisoned = 1;
		dev_warn(dev, "CPU write control disabled %d; retaining read-only provider, no boot request\n", ret);
	}
	platform_set_drvdata(pdev, p);
	ret = vcm_register_clocks(dev, p);
	if (ret)
		return ret;
	p->cpu_starting = true;
	ret = devm_device_add_group(dev, &vcm_group);
	if (ret)
		return ret;
	if (p->cpu_control && p->cpu_boot_hz == 125000000) {
		mutex_lock(&p->lock);
		p->cpu_armed = true; /* Explicit DT boot policy, never the default. */
		ret = vcm_cpu_set_locked(p, p->cpu_boot_hz);
		p->cpu_last_result = ret; /* Include shared-owner preflight rejection. */
		p->cpu_armed = false; /* Runtime writes still require an explicit arm. */
		mutex_unlock(&p->lock);
		if (ret)
			dev_err(dev, "CPU boot target failed %d; confirmed=%u poison=%u; no retry\n",
				ret, p->cpu_transaction.actual_hz, p->cpu_transaction.poisoned);
	}
	mutex_lock(&p->lock);
	if (p->cpu_control && p->fabric_boot_enabled) {
		ret = vcm_fabric_boot_locked(p);
		p->fabric_last_result = ret;
		dev_info(dev, "fabric boot target result=%d confirmed=%u attempted=%u shared_fault=%u\n",
			ret, p->fabric_transaction.actual_hz, p->fabric_attempted, p->rate_fault);
	}
	p->cpu_starting = false;
	mutex_unlock(&p->lock);
	dev_info(dev, "rate ABI2 / CPU meter ABI%u fabric meter ABI1; CPU control=%u boot_target=%u fabric_boot_target=%u attempted=%u runtime_fabric_writes=disabled\n",
		p->cpu_lanes, p->cpu_control, p->cpu_boot_hz, p->fabric_boot_hz, p->fabric_attempted);
	return 0;
}
static const struct of_device_id vcm_match[] = {
	{ .compatible = "openion,valence-clock-monitor-v1" },
	{ .compatible = "openion,valence-a1-runtime-clock-monitor-v2" }, {},
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
MODULE_DESCRIPTION("Valence CMU telemetry and opt-in CPU-only clock control");
MODULE_VERSION(VALENCE_DRIVER_VERSION);
