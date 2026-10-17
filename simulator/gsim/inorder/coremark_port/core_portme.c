#include "coremark.h"
#include <stdarg.h>
volatile ee_s32 seed1_volatile = 0, seed2_volatile = 0, seed3_volatile = 0x66;
volatile ee_s32 seed4_volatile = 1, seed5_volatile = 0;
ee_u32 default_num_contexts = 1;
volatile ee_u32 coremark_validation_errors = 0, coremark_validated = 0;
volatile ee_u32 coremark_crcs[5] = {0};
volatile CORE_TICKS coremark_elapsed_ticks = 0;
static CORETIMETYPE start_tick;
#ifdef I1_COREMARK_SOC
/* Simulator-cycle ROI around retired stores, not DUT time returned as oracle.
 * Same standard2000-byte workload; one iteration, never a formal score. */
volatile ee_u32 coremark_phase = 0;
volatile ee_u32 coremark_duration_warnings = 0;
void start_time(void) { coremark_phase = 1; }
void stop_time(void) { coremark_phase = 2; }
#else
void start_time(void) { start_tick = *(volatile uint64_t *)(uintptr_t)0x0200bff8; }
void stop_time(void) { coremark_elapsed_ticks = *(volatile uint64_t *)(uintptr_t)0x0200bff8 - start_tick; }
#endif
CORE_TICKS get_time(void) { return coremark_elapsed_ticks; }
/* Deliberately NOT a >=10s formal score: fixed one-iteration short architectural acceptance. */
secs_ret time_in_secs(CORE_TICKS ticks) { (void)ticks; return 0; }
void portable_init(core_portable *p, int *argc, char *argv[]) {
    (void)argc; (void)argv; p->portable_id = 1;
}
void portable_fini(core_portable *p) { p->portable_id = 0; }
static int prefix(const char *a, const char *b) {
    while (*b && *a == *b) { ++a; ++b; }
    return !*b;
}
int ee_printf(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    if (prefix(fmt, "seedcrc")) coremark_crcs[0] = (unsigned)va_arg(ap, int);
    else if (prefix(fmt, "[%d]crc")) {
        (void)va_arg(ap, int);
        unsigned value = (unsigned)va_arg(ap, int);
        unsigned which = prefix(fmt, "[%d]crclist") ? 1 : prefix(fmt, "[%d]crcmatrix") ? 2 :
            prefix(fmt, "[%d]crcstate") ? 3 : 4;
        coremark_crcs[which] = value;
    } else if (prefix(fmt, "Correct operation validated")) coremark_validated = 1;
#ifdef I1_COREMARK_SOC
    else if (prefix(fmt, "ERROR! Must execute")) ++coremark_duration_warnings;
#endif
    else if (prefix(fmt, "ERROR!") && !prefix(fmt, "ERROR! Must execute")) ++coremark_validation_errors;
    va_end(ap); return 0;
}
