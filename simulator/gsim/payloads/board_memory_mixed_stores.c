/* Read the same 64 KiB source three times, with sparse stores to one separate
 * scratch line. Initialization, one full source traversal, verification and
 * dirty writeback are outside the single measured interval. */
#define main archived_ddr_bench_main
#include "../../../fpga/firmware/ddr_bench.c"
#undef main

#ifndef MIXED_STORE_LINE_PERIOD
#error "choose MIXED_STORE_LINE_PERIOD=16 or 64 for both guest and host"
#endif
_Static_assert(MIXED_STORE_LINE_PERIOD == 16 || MIXED_STORE_LINE_PERIOD == 64,
               "mixed workload supports only the two qualified store periods");
#define MIXED_SCRATCH_BASE 0x84000000UL
#define MIXED_STORE_SEED 0x5a170000ULL
#define MIXED_STORES (3U * 1024U / MIXED_STORE_LINE_PERIOD)
_Static_assert(MIXED_SCRATCH_BASE >= CHAIN_BASE + MAX_BYTES &&
               MIXED_SCRATCH_BASE + 64 <= SAFE_END, "scratch line overlaps reserved memory");

__attribute__((noinline, noclone)) static uint64_t steady_start(void) {
    uint64_t v; __asm__ volatile("fence rw,rw\nrdtime %0" : "=r"(v) :: "memory"); return v;
}
__attribute__((noinline, noclone)) static uint64_t steady_stop(void) {
    uint64_t v; __asm__ volatile("fence rw,rw\nrdtime %0\nnop" : "=r"(v) :: "memory"); return v;
}
__attribute__((noinline, noclone)) static uint64_t mixed_read_stores(void) {
    const volatile uint64_t *src = (const volatile uint64_t *)SRC_BASE;
    volatile uint64_t *scratch = (volatile uint64_t *)MIXED_SCRATCH_BASE;
    uint64_t a = 0, b = 0, c = 0, d = 0, e = 0, f = 0, g = 0, h = 0;
    unsigned stores = 0;
    for (unsigned pass = 0; pass < 3; ++pass)
        for (unsigned line = 0; line < 1024; ++line) {
            const unsigned i = line * 8;
            a += src[i + 0]; b += src[i + 1]; c += src[i + 2]; d += src[i + 3];
            e += src[i + 4]; f += src[i + 5]; g += src[i + 6]; h += src[i + 7];
            if (((line + 1) & (MIXED_STORE_LINE_PERIOD - 1)) == 0) {
                /* One word per opportunity, rotating through all eight words.
                 * This value has no dependency on any source load or sum. */
                scratch[stores & 7] = MIXED_STORE_SEED + stores;
                ++stores;
            }
        }
    return a + b + c + d + e + f + g + h;
}
int main(void) {
    volatile uint64_t *src = (volatile uint64_t *)SRC_BASE;
    volatile uint64_t *scratch = (volatile uint64_t *)MIXED_SCRATCH_BASE;
    stream_write(src, 8192, 1);
    for (unsigned word = 0; word < 8; ++word) scratch[word] = ~(MIXED_STORE_SEED + word);
    sync_ddr();
    observed = stream_read(src, 8192, 1); /* full pre-traversal, outside markers */
    int ok = observed == expected_sum(8192, 1);
    const uint64_t begin = steady_start();
    const uint64_t sum = mixed_read_stores();
    const uint64_t end = steady_stop();
    observed = sum;
    ok &= sum == expected_sum(8192, 3) && end > begin;
    ok &= verify(src, 8192);
    for (unsigned word = 0; word < 8; ++word)
        ok &= scratch[word] == MIXED_STORE_SEED + MIXED_STORES - 8 + word;
    sync_ddr(); /* make final scratch contents independently visible in backing */
    text("MIXED_READ_STORE working_set=65536 reps=3 source_loads=24576 store_line_period=");
    decimal(MIXED_STORE_LINE_PERIOD); text(" scratch_stores="); decimal(MIXED_STORES);
    text(" ticks="); decimal(end - begin); text(ok ? " PASS\r\n" : " FAIL\r\n");
    text(ok ? "STEADY PASS\r\n" : "STEADY FAIL\r\n");
    return 0;
}
