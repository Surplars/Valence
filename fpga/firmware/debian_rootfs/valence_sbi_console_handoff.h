/* SPDX-License-Identifier: BSD-2-Clause
 * Applied only after OpenSBI has initialized its console. The explicit DT
 * property reserves this UART for SBI; Linux sees it disabled. No UART MMIO
 * or clock state is changed. Initial firmware DT must remain enabled.
 */
#ifndef VALENCE_SBI_CONSOLE_HANDOFF_H
#define VALENCE_SBI_CONSOLE_HANDOFF_H
#include <libfdt.h>
static int valence_sbi_console_handoff(void *fdt)
{
	const char *path, *status;
	const fdt32_t *reg;
	int uart, chosen, len, n;
	uart = fdt_path_offset(fdt, "/soc/serial@10000000");
	if (uart < 0)
		return 0;
	if (!fdt_getprop(fdt, uart, "openion,sbi-console-exclusive", &len))
		return 0;
	if (len != 0 || fdt_node_check_compatible(fdt, uart, "ns16550a"))
		return -FDT_ERR_BADVALUE;
	reg = fdt_getprop(fdt, uart, "reg", &len);
	if (!reg || len != 16 || fdt32_to_cpu(reg[0]) != 0 ||
	    fdt32_to_cpu(reg[1]) != 0x10000000 || fdt32_to_cpu(reg[2]) != 0 ||
	    fdt32_to_cpu(reg[3]) != 8)
		return -FDT_ERR_BADVALUE;
	status = fdt_getprop(fdt, uart, "status", &len);
	if (!status || len != 5 || status[0] != 'o' || status[1] != 'k' ||
	    status[2] != 'a' || status[3] != 'y' || status[4])
		return -FDT_ERR_BADVALUE;
	chosen = fdt_path_offset(fdt, "/chosen");
	path = fdt_getprop(fdt, chosen, "stdout-path", &len);
	if (!path || len < 2 || path[len - 1])
		return -FDT_ERR_BADVALUE;
	for (n = 0; n < len && path[n] && path[n] != ':'; n++)
		;
	if (fdt_path_offset_namelen(fdt, path, n) != uart)
		return -FDT_ERR_BADVALUE;
	return fdt_setprop_string(fdt, uart, "status", "disabled");
}
#endif
