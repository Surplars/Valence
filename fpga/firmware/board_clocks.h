#ifndef VALENCE_BOARD_CLOCKS_H
#define VALENCE_BOARD_CLOCKS_H
#include <stdint.h>

/* CPU_HZ is accepted only for old single-clock build/test callers. New code
 * must use TIMEBASE_HZ for rdtime and CPU_CLOCK_HZ for CPU metadata only. */
#ifndef CPU_HZ
#define CPU_HZ 40000000ULL
#endif
#ifndef TIMEBASE_HZ
#define TIMEBASE_HZ CPU_HZ
#endif
#ifndef BOARD_CPU_CLOCK_HZ
#define BOARD_CPU_CLOCK_HZ CPU_HZ
#endif
#ifndef FABRIC_CLOCK_HZ
#define FABRIC_CLOCK_HZ TIMEBASE_HZ
#endif
#ifndef DDR_UI_CLOCK_HZ
#define DDR_UI_CLOCK_HZ FABRIC_CLOCK_HZ
#endif
#ifndef BOARD_CMU_CLOCKS
#define BOARD_CMU_CLOCKS 0
#endif
_Static_assert(TIMEBASE_HZ > 0 && TIMEBASE_HZ <= 500000000ULL, "invalid rdtime frequency");

#if BOARD_CMU_CLOCKS
#include "valence_cmu.h"
static inline uint64_t board_cpu_clock_hz(void) {
    /* Configured nominal frequency, not an on-board frequency measurement.
     * Never infer the CPU implementation from its rate or fabricate an ID. */
    return valence_cmu_nominal_hz(CMU_CPU);
}
#define CPU_CLOCK_HZ (board_cpu_clock_hz())
#else
#define CPU_CLOCK_HZ ((uint64_t)BOARD_CPU_CLOCK_HZ)
#endif

/* Promote before every multiplication, even if a caller passes an unsuffixed
 * 250000000. The 20-second budget is larger than a 32-bit unsigned integer. */
static inline uint64_t board_seconds_to_ticks(uint32_t seconds) {
    return (uint64_t)TIMEBASE_HZ * seconds;
}
/* All bandwidth kernels report at most 16 MiB including logical read+write.
 * At <=500 MHz the numerator fits 64 bits. Divide before MiB conversion so
 * long rdtime intervals cannot overflow an elapsed*1048576 denominator. */
static inline uint64_t board_milli_mib_per_second(uint64_t bytes, uint64_t ticks) {
    return ticks ? bytes * (uint64_t)TIMEBASE_HZ * 1000ULL / ticks / 1048576ULL : 0;
}
/* Exact floor conversion for supported units (<=1 GHz), without ticks*units
 * overflow. Saturate only when the output itself is unrepresentable. */
static inline uint64_t board_ticks_to_units(uint64_t ticks, uint32_t units) {
    uint64_t whole = ticks / (uint64_t)TIMEBASE_HZ;
    uint64_t fraction = (ticks % (uint64_t)TIMEBASE_HZ) * units / (uint64_t)TIMEBASE_HZ;
    if (units && whole > (UINT64_MAX - fraction) / units) return UINT64_MAX;
    return whole * units + fraction;
}
#endif
