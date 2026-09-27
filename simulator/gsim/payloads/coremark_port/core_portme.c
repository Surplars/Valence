#include "coremark.h"
#include "core_portme.h"

volatile ee_s32 seed1_volatile = 0;
volatile ee_s32 seed2_volatile = 0;
volatile ee_s32 seed3_volatile = 0x66;
volatile ee_s32 seed4_volatile = 1;
volatile ee_s32 seed5_volatile = 0;
ee_u32 default_num_contexts = 1;
volatile ee_u32 coremark_validation_errors = 0;
volatile CORE_TICKS coremark_elapsed_ticks = 0;
static CORETIMETYPE start_tick;

static CORETIMETYPE timer_tick(void) {
    return *(volatile uint64_t *)(uintptr_t)0x0200bff8;
}

void start_time(void) { start_tick = timer_tick(); }
void stop_time(void) { coremark_elapsed_ticks = timer_tick() - start_tick; }
CORE_TICKS get_time(void) { return coremark_elapsed_ticks; }

/* Simulation has no measured physical clock. Keep CoreMark's official
 * ten-second duration check unsatisfied and report guest ticks separately. */
secs_ret time_in_secs(CORE_TICKS ticks) { (void)ticks; return 0; }

void portable_init(core_portable *p, int *argc, char *argv[]) {
    (void)argc; (void)argv;
    p->portable_id = 1;
}
void portable_fini(core_portable *p) { p->portable_id = 0; }

/* Capture official workload CRC failures without spending millions of
 * simulated UART cycles on benchmark formatting. */
int ee_printf(const char *fmt, ...) {
    for (const char *p = fmt; *p; ++p) {
        if (p[0] == 'E' && p[1] == 'R' && p[2] == 'R' && p[3] == 'O' && p[4] == 'R' && p[5] == '!') {
            const char *duration = "ERROR! Must execute";
            const char *a = fmt, *b = duration;
            while (*a && *b && *a == *b) { ++a; ++b; }
            if (*b) ++coremark_validation_errors;
            break;
        }
    }
    return 0;
}
