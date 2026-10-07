/* CPU-visible DDR benchmark for the signed DDR50 / 115200 FIFO-UART bit.
 * Volatile prevents compiler removal, NOT cache bypass. FENCE.I writeback is
 * Valence-specific. UART, initialization and verification are outside timing.
 */
#include <stdint.h>
#include <stddef.h>

#ifndef CPU_HZ
#define CPU_HZ 50000000ULL
#endif
#ifndef UART_BAUD
#define UART_BAUD 115200U
#endif

#define SRC_BASE 0x80400000UL
/* One cache-line offset avoids same-index src/dst thrashing in the 2 KiB L1. */
#define DST_BASE 0x81400040UL
#define CHAIN_BASE 0x83000000UL
#define MAX_BYTES (8UL * 1024 * 1024)
#define SAFE_END 0xa01f8000UL
#define SEED 0x10203040ULL
#define UART ((volatile uint8_t *)0x10000000UL)

_Static_assert(SRC_BASE >= 0x80400000UL && SRC_BASE + MAX_BYTES <= DST_BASE,
               "benchmark overlaps program or source/destination buffers");
_Static_assert(DST_BASE + MAX_BYTES <= CHAIN_BASE && CHAIN_BASE + MAX_BYTES <= SAFE_END,
               "benchmark overlaps chain, application stack or ROM monitor");

static volatile uint64_t observed;
static unsigned errors;

#ifdef DDR_BENCH_HOST_TEST
extern void ddr_bench_host_putc(char c);
#endif
static void putc_uart(char c) {
#ifdef DDR_BENCH_HOST_TEST
    ddr_bench_host_putc(c);
#else
    while (!(UART[5] & 0x20)) {}
    UART[0] = (uint8_t)c;
#endif
}
static void text(const char *s) { while (*s) putc_uart(*s++); }
static void decimal(uint64_t v) {
    char digits[24];
    unsigned n = 0;
    do { digits[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) putc_uart(digits[--n]);
}
static void fixed3(uint64_t milli) {
    decimal(milli / 1000);
    putc_uart('.');
    putc_uart((char)('0' + (milli / 100) % 10));
    putc_uart((char)('0' + (milli / 10) % 10));
    putc_uart((char)('0' + milli % 10));
}
static void hex(uint64_t v) {
    text("0x");
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned d = (unsigned)(v >> shift) & 15;
        putc_uart((char)(d < 10 ? '0' + d : 'a' + d - 10));
    }
}
static int key(void) {
#ifdef DDR_BENCH_HOST_TEST
    return -1;
#else
    return UART[5] & 1 ? UART[0] : -1;
#endif
}
/* Fence orders memory operations; the compiler memory clobber also bounds them.
 * This board increments time once per CPU cycle; cycle/instret are unavailable.
 */
static uint64_t ordered_ticks(void) {
#ifdef DDR_BENCH_HOST_TEST
    __asm__ volatile ("" ::: "memory");
    return 0;
#else
    uint64_t v;
    __asm__ volatile ("fence rw,rw\nrdtime %0" : "=r"(v) :: "memory");
    return v;
#endif
}
static void sync_ddr(void) {
#ifdef DDR_BENCH_HOST_TEST
    __asm__ volatile ("" ::: "memory");
#else
    __asm__ volatile ("fence rw,rw\nfence.i\nfence rw,rw" ::: "memory");
#endif
}

/* All timed kernels are 64-bit, 8-way unrolled, without UART or verification.
 * bytes/8 is a multiple of eight, and repetitions is positive at every call.
 */
static void stream_write(volatile uint64_t *p, size_t words, unsigned repetitions) {
    for (unsigned pass = 0; pass < repetitions; ++pass)
        for (size_t i = 0; i < words; i += 8) {
            p[i + 0] = SEED + i + 0; p[i + 1] = SEED + i + 1;
            p[i + 2] = SEED + i + 2; p[i + 3] = SEED + i + 3;
            p[i + 4] = SEED + i + 4; p[i + 5] = SEED + i + 5;
            p[i + 6] = SEED + i + 6; p[i + 7] = SEED + i + 7;
        }
}
static uint64_t stream_read(const volatile uint64_t *p, size_t words, unsigned repetitions) {
    uint64_t a = 0, b = 0, c = 0, d = 0;
    uint64_t e = 0, f = 0, g = 0, h = 0;
    for (unsigned pass = 0; pass < repetitions; ++pass)
        for (size_t i = 0; i < words; i += 8) {
            a += p[i + 0]; b += p[i + 1]; c += p[i + 2]; d += p[i + 3];
            e += p[i + 4]; f += p[i + 5]; g += p[i + 6]; h += p[i + 7];
        }
    return a + b + c + d + e + f + g + h;
}
static void stream_copy(volatile uint64_t *dst, const volatile uint64_t *src,
                        size_t words, unsigned repetitions) {
    for (unsigned pass = 0; pass < repetitions; ++pass)
        for (size_t i = 0; i < words; i += 8) {
            uint64_t a = src[i + 0], b = src[i + 1], c = src[i + 2], d = src[i + 3];
            uint64_t e = src[i + 4], f = src[i + 5], g = src[i + 6], h = src[i + 7];
            dst[i + 0] = a; dst[i + 1] = b; dst[i + 2] = c; dst[i + 3] = d;
            dst[i + 4] = e; dst[i + 5] = f; dst[i + 6] = g; dst[i + 7] = h;
        }
}
static uint64_t expected_sum(size_t words, unsigned repetitions) {
    return ((uint64_t)words * SEED + (uint64_t)words * (words - 1) / 2) * repetitions;
}
static int verify(const volatile uint64_t *p, size_t words) {
    for (size_t i = 0; i < words; ++i) {
        uint64_t v = p[i], expected = SEED + i;
        if (v != expected) {
            ++errors;
            text("VERIFY FAIL addr="); hex((uintptr_t)&p[i]);
            text(" expected="); hex(expected); text(" actual="); hex(v); text("\r\n");
            return 0;
        }
    }
    return 1;
}
static uint64_t rate_milli_mib(uint64_t bytes, uint64_t elapsed) {
    /* Bounded to <=8 MiB per reported streaming result; no 128-bit runtime needed. */
    return elapsed ? bytes * CPU_HZ * 1000 / (elapsed * 1048576ULL) : 0;
}
static int report(const char *name, uint64_t bytes, uint64_t elapsed, int ok,
                  int copy) {
    if (!elapsed) { ++errors; ok = 0; }
    text(name); text(" bytes="); decimal(bytes);
    text(" ticks="); decimal(elapsed);
    text(" ms="); fixed3(elapsed * 1000000ULL / CPU_HZ);
    text(" MiB/s="); fixed3(rate_milli_mib(bytes, elapsed));
    if (copy) {
        text(" logical_R+W_MiB/s="); fixed3(rate_milli_mib(bytes * 2, elapsed));
    }
    text(ok ? " PASS\r\n" : " FAIL\r\n");
    return ok;
}
static int streams(size_t bytes, unsigned repetitions) {
    volatile uint64_t *src = (volatile uint64_t *)SRC_BASE;
    volatile uint64_t *dst = (volatile uint64_t *)DST_BASE;
    size_t words = bytes / 8;
    text("STREAM working_set="); decimal(bytes);
    text(" repetitions="); decimal(repetitions); text("\r\n");

    stream_write(src, words, 1);
    sync_ddr();
    uint64_t start = ordered_ticks();
    uint64_t sum = stream_read(src, words, repetitions);
    uint64_t elapsed = ordered_ticks() - start;
    observed = sum;
    int ok = sum == expected_sum(words, repetitions);
    if (!ok) ++errors;
    if (!report("READ(cold-start)", bytes * repetitions, elapsed, ok, 0)) return 0;

    sync_ddr();
    start = ordered_ticks();
    stream_write(src, words, repetitions);
    sync_ddr(); /* Include completion of dirty writeback, not just cache acceptance. */
    elapsed = ordered_ticks() - start;
    if (!report("WRITE(+flush)", bytes * repetitions, elapsed, verify(src, words), 0)) return 0;

    /* Poison destination outside timing so missing copy stores cannot pass. */
    for (size_t i = 0; i < words; ++i) dst[i] = ~(SEED + i);
    sync_ddr();
    start = ordered_ticks();
    stream_copy(dst, src, words, repetitions);
    sync_ddr();
    elapsed = ordered_ticks() - start;
    return report("COPY(payload,+flush)", bytes * repetitions, elapsed, verify(dst, words), 1);
}
static int hot_read(void) {
    const size_t words = 1024 / 8;
    const unsigned repetitions = 64;
    volatile uint64_t *p = (volatile uint64_t *)SRC_BASE;
    stream_write(p, words, 1);
    sync_ddr();
    observed = stream_read(p, words, 1); /* Warm the entire working set before start. */
    uint64_t start = ordered_ticks();
    uint64_t sum = stream_read(p, words, repetitions);
    uint64_t elapsed = ordered_ticks() - start;
    observed = sum;
    int ok = sum == expected_sum(words, repetitions);
    if (!ok) ++errors;
    return report("CACHE_READ(1KiB,warm)", 1024ULL * repetitions, elapsed, ok, 0);
}

/* Power-of-two node count and odd step produce one full-period ring.
 * One pointer per 64-byte line, no line reused until the complete traversal.
 * Dependent volatile loads prevent OoO overlap; latency includes the CPU path
 * and loop overhead. It is not a bare DRAM tCAS or PHY-latency measurement.
 */
static void build_chain(uintptr_t base, size_t bytes) {
    size_t nodes = bytes / 64;
    for (size_t i = 0; i < nodes; ++i)
        *(volatile uintptr_t *)(base + i * 64) = base + ((i + 257) & (nodes - 1)) * 64;
}
static uintptr_t walk_chain(uintptr_t p, size_t hops) {
    for (size_t i = 0; i < hops; i += 8) {
        p = *(volatile uintptr_t *)p; p = *(volatile uintptr_t *)p;
        p = *(volatile uintptr_t *)p; p = *(volatile uintptr_t *)p;
        p = *(volatile uintptr_t *)p; p = *(volatile uintptr_t *)p;
        p = *(volatile uintptr_t *)p; p = *(volatile uintptr_t *)p;
    }
    return p;
}
static int chase(size_t bytes) {
    size_t hops = bytes / 64;
    build_chain(CHAIN_BASE, bytes);
    sync_ddr();
    uint64_t start = ordered_ticks();
    uintptr_t last = walk_chain(CHAIN_BASE, hops);
    uint64_t elapsed = ordered_ticks() - start;
    observed = last;
    int ok = elapsed && last == CHAIN_BASE;
    if (!ok) ++errors;
    text("CHASE working_set="); decimal(bytes);
    text(" hops="); decimal(hops); text(" ticks="); decimal(elapsed);
    text(" ticks/hop="); fixed3(elapsed * 1000 / hops);
    text(" ns/hop="); fixed3((elapsed * 1000000000ULL / CPU_HZ) * 1000 / hops);
    text(ok ? " PASS\r\n" : " FAIL\r\n");
    return ok;
}
static void run_bench(char command) {
    errors = 0;
    int ok;
    if (command == 's') ok = streams(4096, 1) && chase(4096);
    else if (command == 'q')
        ok = hot_read() && streams(65536, 4) && streams(1048576, 1) && chase(1048576);
    else ok = streams(MAX_BYTES, 1) && chase(MAX_BYTES);
    text("DDR BENCH "); text(ok && !errors ? "PASS" : "FAIL");
    text(" errors="); decimal(errors); text("\r\n");
}
#ifdef DDR_BENCH_LOCALITY
/* Same kernels and addresses as the DDR smoke. Eight bounded regions per size;
 * copy has TWO buffers, so its footprint is twice the reported per-buffer size.
 * Keep marker PCs unique for passive retirement-delimited hardware counters. */
__attribute__((noinline, noclone)) static uint64_t locality_start(void) {
    uint64_t v;
    __asm__ volatile ("fence rw,rw\nrdtime %0" : "=r"(v) :: "memory");
    return v;
}
__attribute__((noinline, noclone)) static uint64_t locality_stop(void) {
    uint64_t v;
    __asm__ volatile ("fence rw,rw\nrdtime %0\nnop" : "=r"(v) :: "memory");
    return v;
}
static void locality_result(size_t bytes, const char *phase, uint64_t ticks, int ok) {
    if (!ok || !ticks) ++errors;
    text("LOCALITY size="); decimal(bytes); text(" phase="); text(phase);
    text(" ticks="); decimal(ticks); text(ok && ticks ? " PASS\r\n" : " FAIL\r\n");
}
static void locality(void) {
    volatile uint64_t *src=(volatile uint64_t *)SRC_BASE;
    volatile uint64_t *dst=(volatile uint64_t *)DST_BASE;
    errors=0;
    for (size_t bytes=1024; bytes<=8192; bytes*=2) {
        const size_t words=bytes/8;
        uint64_t start, elapsed, sum;
        stream_write(src,words,1); sync_ddr();
        start=locality_start(); sum=stream_read(src,words,1); elapsed=locality_stop()-start;
        observed=sum; locality_result(bytes,"read_cold_1",elapsed,sum==expected_sum(words,1));
        observed=stream_read(src,words,1);
        start=locality_start(); sum=stream_read(src,words,3); elapsed=locality_stop()-start;
        observed=sum; locality_result(bytes,"read_warm_3",elapsed,sum==expected_sum(words,3));
        for(size_t i=0;i<words;++i) src[i]=~(SEED+i);
        sync_ddr(); observed=stream_read(src,words,1);
        start=locality_start(); stream_write(src,words,3); elapsed=locality_stop()-start;
        const uint64_t write_elapsed=elapsed, write_start=start;
        start=locality_start(); sync_ddr(); elapsed=locality_stop()-start;
        const uint64_t write_complete=start+elapsed-write_start;
        const int write_ok=verify(src,words);
        locality_result(bytes,"write_warm_3",write_elapsed,write_ok);
        locality_result(bytes,"write_flush",elapsed,write_ok);
        text("COMPLETE size="); decimal(bytes); text(" phase=write ticks="); decimal(write_complete); text("\r\n");
        for(size_t i=0;i<words;++i) dst[i]=~(SEED+i);
        sync_ddr(); observed=stream_read(src,words,1); observed=stream_read(dst,words,1);
        start=locality_start(); stream_copy(dst,src,words,3); elapsed=locality_stop()-start;
        const uint64_t copy_elapsed=elapsed, copy_start=start;
        start=locality_start(); sync_ddr(); elapsed=locality_stop()-start;
        const uint64_t copy_complete=start+elapsed-copy_start;
        const int copy_ok=verify(dst,words);
        locality_result(bytes,"copy_warm_3",copy_elapsed,copy_ok);
        locality_result(bytes,"copy_flush",elapsed,copy_ok);
        text("COMPLETE size="); decimal(bytes); text(" phase=copy ticks="); decimal(copy_complete); text("\r\n");
        build_chain(CHAIN_BASE,bytes); sync_ddr();
        start=locality_start(); uintptr_t last=walk_chain(CHAIN_BASE,bytes/64); elapsed=locality_stop()-start;
        observed=last; locality_result(bytes,"chase_cold_1",elapsed,last==CHAIN_BASE);
        observed=walk_chain(CHAIN_BASE,bytes/64);
        start=locality_start(); last=walk_chain(CHAIN_BASE,3*bytes/64); elapsed=locality_stop()-start;
        observed=last; locality_result(bytes,"chase_warm_3",elapsed,last==CHAIN_BASE);
    }
    sync_ddr(); text(errors ? "LOCALITY FAIL\r\n" : "LOCALITY PASS\r\n");
}
#endif

int main(void) {
    text("\r\nValence DDR benchmark V0.1 - CPU "); decimal(CPU_HZ / 1000000);
    text(" MHz, UART "); decimal(UART_BAUD); text(" 8N1\r\n");
#ifdef DDR_BENCH_LOCALITY
    text("CPU-visible coherent write-back L1, capacity under test, 64B lines.\r\n");
#else
    text("CPU-visible path, 2KiB write-back L1, 64B lines; NOT MIG peak bandwidth.\r\n");
#endif
    text("rdtime clock="); decimal(CPU_HZ); text(" Hz; no UART in timed regions.\r\n");
    text("Destructive buffers: 0x80400000/0x81400040/0x83000000, up to 8MiB each.\r\n");
    text("COPY reports payload and logical R+W, not actual AXI bytes.\r\n");
    text("Auto 4KiB smoke only; use q/b for representative streaming results.\r\n");
#ifdef DDR_BENCH_LOCALITY
    locality(); return 0;
#endif
    run_bench('s');
    for (;;) {
        text("[s] 4KiB smoke [q] 64KiB/1MiB+cache [b] 8MiB [x] return to Bootrom\r\n");
        int c;
        do { c = key(); } while (c != 's' && c != 'q' && c != 'b' && c != 'x');
        if (c == 'x') { sync_ddr(); return 0; }
        run_bench((char)c);
    }
}
