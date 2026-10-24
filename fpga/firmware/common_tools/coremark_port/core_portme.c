#define _POSIX_C_SOURCE 200809L
#include "coremark.h"
#include <time.h>
#include <stdlib.h>
ee_u32 default_num_contexts = 1;
static CORE_TICKS started, elapsed;
static CORE_TICKS now_ns(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) abort();
    return (CORE_TICKS)now.tv_sec * 1000000000ULL + now.tv_nsec;
}
void start_time(void) { started = now_ns(); }
void stop_time(void) { elapsed = now_ns() - started; }
CORE_TICKS get_time(void) { return elapsed; }
secs_ret time_in_secs(CORE_TICKS ticks) { return (double)ticks / 1000000000.0; }
void portable_init(core_portable *p, int *argc, char *argv[])
{
    (void)argc; (void)argv; p->portable_id = 1;
}
void portable_fini(core_portable *p) { p->portable_id = 0; }
