// SPDX-License-Identifier: GPL-2.0-only
/* Single-hart Valence APLIC + CSR-only IMSIC adapter, NOT a standard IMSIC.
 * No CPU MSI aperture, no IPI/MSI allocator, no CPU hotplug. Fixed EIID=source.
 * The upstream RISC-V INTC handles SEIP; this is its chained child IRQ domain.
 */
#include "valence_driver_names.h"
#define pr_fmt(fmt) VALENCE_AIA_DRIVER ": " fmt
#include <linux/completion.h>
#include <linux/cpu.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/irq.h>
#include <linux/irqchip/chained_irq.h>
#include <linux/irqdomain.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <asm/asm-extable.h>
#include <asm/csr.h>
#include "valence_irq_policy.h"

#define A_DOMAIN 0x0000
#define A_SOURCE(n) (4 * (n))
#define A_SETIPNUM 0x1cdc
#define A_INPUT 0x1d00
#define A_CLRIPNUM 0x1ddc
#define A_SETIE 0x1e00
#define A_CLRIE 0x1f00
#define A_GENMSI 0x3000
#define A_TARGET(n) (0x3000 + 4 * (n))
#define I_DELIVERY 0x70
#define I_THRESHOLD 0x72
#define I_PENDING0 0x80
#define I_PENDING1 0x82
#define I_ENABLE0 0xc0
#define I_ENABLE1 0xc2

struct vaia {
	struct device *dev;
	void __iomem *root, *leaf;
	struct irq_domain *domain;
	raw_spinlock_t lock;
	struct completion selftest;
	u32 levels;
	unsigned int parent_irq;
	u64 parent_calls, claims, selftest_irqs;
	bool ready, faulted;
};

/* Exception-table guarded discovery: the wrong bit must not Oops the kernel. */
static int va_probe_csrs(void)
{
	unsigned long value;
	int error = 0;

	asm volatile("1: csrw 0x150, %2\n"
		     "2: csrr %0, 0x151\n"
		     "3: csrr %0, 0x15c\n"
		     "4:\n"
		     _ASM_EXTABLE_UACCESS_ERR(1b, 4b, %1)
		     _ASM_EXTABLE_UACCESS_ERR(2b, 4b, %1)
		     _ASM_EXTABLE_UACCESS_ERR(3b, 4b, %1)
		     : "=&r" (value), "+&r" (error) : "r" (I_DELIVERY) : "memory");
	return error ? error : (value ? -EBUSY : 0);
}

static void va_reg_write(unsigned int selector, unsigned long value)
{
	csr_write(CSR_SISELECT, selector);
	csr_write(CSR_SIREG, value);
}

static void va_enable(unsigned int source, bool enable)
{
	csr_write(CSR_SISELECT, I_ENABLE0);
	if (enable)
		csr_set(CSR_SIREG, BIT(source));
	else
		csr_clear(CSR_SIREG, BIT(source));
}

static void va_mask(struct irq_data *d)
{
	struct vaia *p = irq_data_get_irq_chip_data(d);
	unsigned long flags;

	raw_spin_lock_irqsave(&p->lock, flags);
	writel(BIT(d->hwirq), p->leaf + A_CLRIE);
	va_enable(d->hwirq, false);
	raw_spin_unlock_irqrestore(&p->lock, flags);
}

static void va_unmask(struct irq_data *d)
{
	struct vaia *p = irq_data_get_irq_chip_data(d);
	unsigned long flags;

	raw_spin_lock_irqsave(&p->lock, flags);
	if (!p->faulted) {
		va_enable(d->hwirq, true);
		writel(BIT(d->hwirq), p->leaf + A_SETIE);
		/* This APLIC does not automatically re-send a held level.
		 * Re-test its input after unmask; a concurrent new edge is retained.
		 * SETIPNUM is ignored by hardware if the input has since deasserted. */
		if (va_retrigger_level(p->levels, d->hwirq, readl(p->leaf + A_INPUT)))
			writel(d->hwirq, p->leaf + A_SETIPNUM);
	}
	raw_spin_unlock_irqrestore(&p->lock, flags);
}

static void va_ack(struct irq_data *d)
{
	struct vaia *p = irq_data_get_irq_chip_data(d);

	/* STOPEI was already claimed by the parent handler. */
	writel(d->hwirq, p->leaf + A_CLRIPNUM);
}

/* Caller holds lock with IRQs disabled. Inactive mode clears target on EVERY
 * hardware cycle, not only on SOURCECFG writes: activate before retargeting. */
static int va_program_source(struct vaia *p, unsigned int source, u32 mode)
{
	writel(0, p->leaf + A_SOURCE(source));
	writel(mode, p->leaf + A_SOURCE(source));
	writel(source, p->leaf + A_TARGET(source));
	if (readl(p->leaf + A_SOURCE(source)) != mode ||
	    readl(p->leaf + A_TARGET(source)) != source)
		return -EIO;
	return 0;
}

static int va_set_type(struct irq_data *d, unsigned int type)
{
	struct vaia *p = irq_data_get_irq_chip_data(d);
	unsigned long flags;
	u32 mode;
	int ret;

	if (type == IRQ_TYPE_LEVEL_HIGH)
		mode = 6;
	else if (type == IRQ_TYPE_EDGE_RISING)
		mode = 4;
	else
		return -EINVAL;
	raw_spin_lock_irqsave(&p->lock, flags);
	ret = va_program_source(p, d->hwirq, mode);
	if (ret)
		goto unlock;
	if (type == IRQ_TYPE_LEVEL_HIGH)
		p->levels |= BIT(d->hwirq);
	else
		p->levels &= ~BIT(d->hwirq);
	irq_set_handler_locked(d, type == IRQ_TYPE_LEVEL_HIGH ? handle_level_irq : handle_edge_irq);
	irqd_set_trigger_type(d, type);
unlock:
	raw_spin_unlock_irqrestore(&p->lock, flags);
	return ret;
}

static struct irq_chip va_chip = {
	.name = VALENCE_AIA_DRIVER,
	.irq_mask = va_mask,
	.irq_unmask = va_unmask,
	.irq_ack = va_ack,
	.irq_set_type = va_set_type,
	.flags = IRQCHIP_SET_TYPE_MASKED,
};

static int va_map(struct irq_domain *domain, unsigned int virq, irq_hw_number_t hwirq)
{
	struct vaia *p = domain->host_data;
	unsigned long flags;
	int ret;

	if (!va_valid_source(hwirq))
		return -EINVAL;
	raw_spin_lock_irqsave(&p->lock, flags);
	/* Delegate this source from the M root; root IE does not gate S delivery. */
	writel(0x400, p->root + A_SOURCE(hwirq));
	ret = readl(p->root + A_SOURCE(hwirq)) == 0x400 ?
		va_program_source(p, hwirq, 6) : -EIO;
	if (!ret)
		p->levels |= BIT(hwirq);
	raw_spin_unlock_irqrestore(&p->lock, flags);
	if (ret)
		return ret;
	irq_domain_set_info(domain, virq, hwirq, &va_chip, p, handle_level_irq, NULL, NULL);
	return 0;
}

static const struct irq_domain_ops va_domain_ops = {
	.map = va_map,
	.xlate = irq_domain_xlate_twocell,
};

static void va_parent(struct irq_desc *desc)
{
	struct vaia *p = irq_desc_get_handler_data(desc);
	struct irq_chip *chip = irq_desc_get_chip(desc);
	unsigned int count;
	unsigned long word;

	chained_irq_enter(chip, desc);
	p->parent_calls++;
	for (count = 0; count < VA_CLAIM_BUDGET; count++) {
		/* CSRRW with zero claims; a pure CSR read would NOT clear pending. */
		word = csr_swap(CSR_STOPEI, 0);
		if (!word)
			break;
		if (!va_claim_valid(word) ||
		    generic_handle_domain_irq(p->domain, va_claim_id(word))) {
			p->faulted = true;
			break;
		}
		p->claims++;
	}
	if (count == VA_CLAIM_BUDGET)
		p->faulted = true;
	if (p->faulted) {
		va_reg_write(I_DELIVERY, 0);
		dev_err_ratelimited(p->dev, "IRQ claim fault/storm; delivery disabled, reset board\n");
	}
	chained_irq_exit(chip, desc);
}

static irqreturn_t va_test_irq(int irq, void *data)
{
	struct vaia *p = data;

	p->selftest_irqs++;
	complete(&p->selftest);
	return IRQ_HANDLED;
}

static ssize_t irqchip_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct vaia *p = dev_get_drvdata(dev);

	return sysfs_emit(buf, "ready=%u faulted=%u selftest_irqs=%llu claims=%llu parent_calls=%llu\n",
			  p->ready, p->faulted, p->selftest_irqs, p->claims, p->parent_calls);
}
static DEVICE_ATTR_RO(irqchip_status);
static struct attribute *va_attrs[] = { &dev_attr_irqchip_status.attr, NULL };
static const struct attribute_group va_group = { .attrs = va_attrs };

static int va_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct vaia *p;
	unsigned int test_irq;
	unsigned long flags;
	int ret;

	if (IS_ENABLED(CONFIG_SMP) || num_possible_cpus() != 1)
		return dev_err_probe(dev, -EINVAL, "CSR-only adapter requires one hart, no hotplug\n");
	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->dev = dev;
	raw_spin_lock_init(&p->lock);
	init_completion(&p->selftest);
	p->root = devm_platform_ioremap_resource(pdev, 0);
	p->leaf = devm_platform_ioremap_resource(pdev, 1);
	if (IS_ERR(p->root) || IS_ERR(p->leaf))
		return IS_ERR(p->root) ? PTR_ERR(p->root) : PTR_ERR(p->leaf);
	if ((readl(p->root + A_DOMAIN) & ~BIT(8)) != 0x80000004 ||
	    (readl(p->leaf + A_DOMAIN) & ~BIT(8)) != 0x80000004)
		return dev_err_probe(dev, -ENODEV, "unexpected MSI-only APLIC ABI\n");
	ret = va_probe_csrs();
	if (ret)
		return dev_err_probe(dev, ret, "IMSIC CSR discovery failed; use qualified native bit\n");
	ret = platform_get_irq(pdev, 0);
	if (ret < 0)
		return ret;
	p->parent_irq = ret;
	if (irq_has_action(p->parent_irq) || irq_get_handler_data(p->parent_irq))
		return dev_err_probe(dev, -EBUSY, "SEIP already has an owner\n");
	local_irq_save(flags);
	va_reg_write(I_DELIVERY, 0);
	va_reg_write(I_THRESHOLD, 0);
	va_reg_write(I_ENABLE0, 0);
	va_reg_write(I_ENABLE1, 0);
	va_reg_write(I_PENDING0, 0);
	va_reg_write(I_PENDING1, 0);
	writel(0xfffffffe, p->leaf + A_CLRIE);
	writel(0x80000104, p->leaf + A_DOMAIN);
	local_irq_restore(flags);
	p->domain = irq_domain_create_linear(dev_fwnode(dev), VA_SOURCES + 1, &va_domain_ops, p);
	if (!p->domain)
		return -ENOMEM;
	irq_set_chained_handler_and_data(p->parent_irq, va_parent, p);
	enable_percpu_irq(p->parent_irq, IRQ_TYPE_NONE);
	local_irq_save(flags);
	va_reg_write(I_DELIVERY, 1);
	local_irq_restore(flags);
	test_irq = irq_create_mapping(p->domain, VA_SELFTEST_SOURCE);
	if (!test_irq) {
		ret = -ENOMEM;
		goto disable;
	}
	ret = irq_set_irq_type(test_irq, IRQ_TYPE_EDGE_RISING);
	if (ret)
		goto dispose;
	ret = request_irq(test_irq, va_test_irq, 0, "valence-msi-selftest", p);
	if (ret)
		goto dispose;
	writel(VA_SELFTEST_SOURCE, p->leaf + A_GENMSI);
	ret = wait_for_completion_timeout(&p->selftest, msecs_to_jiffies(1000)) ? 0 : -ETIMEDOUT;
	if (!ret && !p->faulted) {
		/* GENMSI bypasses sourcecfg/target/enable. Also test that path using
		 * an otherwise unused edge source; this catches a lost target write. */
		reinit_completion(&p->selftest);
		writel(VA_SELFTEST_SOURCE, p->leaf + A_SETIPNUM);
		ret = wait_for_completion_timeout(&p->selftest, msecs_to_jiffies(1000)) ? 0 : -ETIMEDOUT;
	}
	free_irq(test_irq, p);
	if (ret || p->faulted || p->selftest_irqs != 2) {
		ret = ret ? ret : -EIO;
		dev_err(dev, "MSI/APLIC -> SEIP -> Linux IRQ selftests failed; MAC stays disabled\n");
		goto dispose;
	}
	p->ready = true;
	platform_set_drvdata(pdev, p);
	ret = devm_device_add_group(dev, &va_group);
	if (ret)
		goto dispose;
	dev_info(dev, "MSI/SEIP selftest PASS; APLIC source test PASS; CSR-only domain, DMA source 6\n");
	return 0;
dispose:
	irq_dispose_mapping(test_irq);
disable:
	disable_percpu_irq(p->parent_irq);
	local_irq_save(flags);
	va_reg_write(I_DELIVERY, 0);
	va_reg_write(I_ENABLE0, 0);
	va_reg_write(I_ENABLE1, 0);
	writel(0xfffffffe, p->leaf + A_CLRIE);
	local_irq_restore(flags);
	irq_set_chained_handler_and_data(p->parent_irq, NULL, NULL);
	irq_domain_remove(p->domain);
	return ret;
}

static const struct of_device_id va_match[] = {
	{ .compatible = "openion,valence-aia-csr-v1" }, { }
};
MODULE_DEVICE_TABLE(of, va_match);
static struct platform_driver va_driver = {
	.probe = va_probe,
	.driver = {
		.name = VALENCE_AIA_DRIVER,
		.of_match_table = va_match,
		.suppress_bind_attrs = true,
	},
};
static int __init va_init(void)
{
	return platform_driver_register(&va_driver);
}
module_init(va_init);
MODULE_DESCRIPTION("Valence single-hart CSR-only APLIC/IMSIC IRQ adapter");
MODULE_AUTHOR(VALENCE_VENDOR);
MODULE_VERSION(VALENCE_DRIVER_VERSION);
MODULE_LICENSE("GPL");
