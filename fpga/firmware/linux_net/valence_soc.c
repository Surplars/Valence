// SPDX-License-Identifier: GPL-2.0-only
/* Board configuration identity, not a probed silicon revision/serial number. */
#include "valence_driver_names.h"
#define pr_fmt(fmt) "valence-soc: " fmt
#include <linux/err.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/sys_soc.h>

static struct soc_device_attribute valence_identity = {
	.family = "OpenIon Valence",
	.soc_id = "VL100",
};

static int __init valence_soc_init(void)
{
	struct soc_device *soc;
	int ret;

	if (!of_machine_is_compatible("openion,valence-vl100"))
		return -ENODEV;
	ret = soc_attr_read_machine(&valence_identity);
	if (ret)
		return ret;
	soc = soc_device_register(&valence_identity);
	if (IS_ERR_OR_NULL(soc))
		return soc ? PTR_ERR(soc) : -ENODEV;
	pr_info("OpenIon VL100 / Orbital-A1; identity from DT, no silicon revision register\n");
	return 0;
}
module_init(valence_soc_init);
MODULE_AUTHOR(VALENCE_VENDOR);
MODULE_DESCRIPTION("OpenIon Valence VL100 board configuration identity");
MODULE_VERSION(VALENCE_DRIVER_VERSION);
MODULE_LICENSE("GPL");
