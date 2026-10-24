/* SPDX-License-Identifier: MIT */
/* User-owned memory only. CPU-visible workload rates, never DDR/MIG peak. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static volatile uint64_t sink;
static uint64_t now_ns(clockid_t clock_id)
{
    struct timespec t;
    if (clock_gettime(clock_id, &t)) { perror("clock_gettime"); exit(1); }
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
}
static unsigned number(const char *s, unsigned low, unsigned high)
{
    char *end;
    errno = 0;
    unsigned long value = strtoul(s, &end, 10);
    if (errno || !*s || *end || *s == '-' || value < low || value > high) {
        fprintf(stderr, "integer required in %u..%u: %s\n", low, high, s);
        exit(2);
    }
    return (unsigned)value;
}
static uint64_t pattern(size_t i, unsigned seed)
{
    return (UINT64_C(0x9e3779b97f4a7c15) * (i + 1)) ^
           (UINT64_C(0xa5f0c39e16782bd4) + seed);
}
struct buffer { unsigned char *base; uint64_t *data; size_t bytes; };
static struct buffer allocate(size_t bytes)
{
    struct buffer b = { .bytes = bytes };
    if (posix_memalign((void **)&b.base, 64, bytes + 128)) {
        fprintf(stderr, "private buffer allocation failed: %zu bytes\n", bytes);
        exit(1);
    }
    b.data = (uint64_t *)(b.base + 64);
    memset(b.base, 0xa7, 64);
    memset(b.base + 64 + bytes, 0xa7, 64);
    return b;
}
static void guards(const struct buffer *b)
{
    for (size_t i = 0; i < 64; i++)
        if (b->base[i] != 0xa7 || b->base[64 + b->bytes + i] != 0xa7) {
            fputs("MEM_BENCH_FAIL guard damaged\n", stderr); exit(1);
        }
}
static uint64_t fill(struct buffer *b, unsigned seed)
{
    uint64_t sum = 0;
    for (size_t i = 0; i < b->bytes / 8; i++) sum += (b->data[i] = pattern(i, seed));
    return sum;
}
static uint64_t read_words(const struct buffer *b)
{
    const volatile uint64_t *p = b->data;
    uint64_t sum = 0;
    for (size_t i = 0; i < b->bytes / 8; i++) sum += p[i];
    return sum;
}
static void pressure(struct buffer *eviction)
{
    volatile uint64_t *p = eviction->data;
    uint64_t sum = 0;
    /* Touch every word in an independent allocation; not an architectural flush. */
    for (size_t i = 0; i < eviction->bytes / 8; i++) { p[i] += 1; sum += p[i]; }
    sink = sum;
}
static void report(const char *op, const char *mode, size_t bytes, unsigned repeats,
                   uint64_t wall, uint64_t cpu, size_t eviction_bytes)
{
    if (!wall) { fputs("zero timer interval\n", stderr); exit(1); }
    double rate = (double)bytes * repeats * 1e9 / (double)wall / 1048576.0;
    printf("{\"operation\":\"%s\",\"mode\":\"%s\",\"buffer_bytes\":%zu,"
           "\"iterations\":%u,\"timed_payload_bytes\":%" PRIu64 ","
           "\"wall_ns\":%" PRIu64 ",\"cpu_ns\":%" PRIu64 ","
           "\"payload_mib_s\":%.6f,\"logical_read_write_mib_s\":%.6f,"
           "\"eviction_bytes\":%zu,\"very_short_interval\":%s,\"verified\":true,\"cache_flush\":false}\n",
           op, mode, bytes, repeats, (uint64_t)bytes * repeats, wall, cpu, rate,
           !strcmp(op, "copy") ? rate * 2.0 : rate, eviction_bytes, wall < 1000000 ? "true" : "false");
    fflush(stdout);
}
static void run_size(size_t bytes, unsigned repeats, int mode, struct buffer *eviction)
{
    struct buffer a = allocate(bytes), b = allocate(bytes);
    uint64_t expected = fill(&a, 7);
    fill(&b, 11);
    for (unsigned phase = 0; phase < 3; phase++) {
        uint64_t wall = 0, cpu = 0;
        for (unsigned r = 0; r < repeats; r++) {
            if (mode) pressure(eviction);
            else { sink = read_words(&a); sink = read_words(&b); }
            uint64_t c0 = now_ns(CLOCK_PROCESS_CPUTIME_ID), w0 = now_ns(CLOCK_MONOTONIC_RAW);
            if (phase == 0) {
                sink = read_words(&a);
            } else if (phase == 1) {
                volatile uint64_t *p = b.data;
                for (size_t i = 0; i < bytes / 8; i++) p[i] = pattern(i, r + 31);
            } else {
                memcpy(b.data, a.data, bytes);
                __asm__ volatile("" : : "r"(b.data) : "memory");
            }
            wall += now_ns(CLOCK_MONOTONIC_RAW) - w0;
            cpu += now_ns(CLOCK_PROCESS_CPUTIME_ID) - c0;
#ifdef VALENCE_TEST_CORRUPT
            if (phase == 1) b.data[0] ^= 1;
#endif
            /* Every iteration is checked, outside its timed interval. */
            if (phase == 0 && sink != expected) {
                fputs("MEM_BENCH_FAIL read checksum\n", stderr); exit(1);
            }
            if (phase == 1)
                for (size_t i = 0; i < bytes / 8; i++)
                    if (b.data[i] != pattern(i, r + 31)) {
                        fprintf(stderr, "MEM_BENCH_FAIL write word=%zu\n", i); exit(1);
                    }
            if (phase == 2 && memcmp(a.data, b.data, bytes)) {
                fputs("MEM_BENCH_FAIL copy mismatch\n", stderr); exit(1);
            }
            guards(&a); guards(&b); guards(eviction);
        }
        report((const char *[]) {"read64", "write64", "copy"}[phase],
               mode ? "eviction_pressure_not_guaranteed_cold" : "warmed_not_guaranteed_cached",
               bytes, repeats, wall, cpu, mode ? eviction->bytes : 0);
    }
    free(a.base); free(b.base);
}
int main(int argc, char **argv)
{
    unsigned repeats = 3, evict_mib = 16;
    const char *sizes_arg = "32,256,4096,16384", *modes = "both";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--help")) {
            puts("valence-mem-bench [--sizes-kib 32,256,4096,16384] [--iterations 1..32] "
                 "[--mode warmed|pressure|both] [--eviction-mib 1..256]");
            return 0;
        }
        if (i + 1 == argc) { fputs("missing argument\n", stderr); return 2; }
        if (!strcmp(argv[i], "--sizes-kib")) sizes_arg = argv[++i];
        else if (!strcmp(argv[i], "--iterations")) repeats = number(argv[++i], 1, 32);
        else if (!strcmp(argv[i], "--eviction-mib")) evict_mib = number(argv[++i], 1, 256);
        else if (!strcmp(argv[i], "--mode")) modes = argv[++i];
        else { fprintf(stderr, "unknown option: %s\n", argv[i]); return 2; }
    }
    if (strcmp(modes, "warmed") && strcmp(modes, "pressure") && strcmp(modes, "both")) {
        fputs("unknown mode\n", stderr); return 2;
    }
    if (!*sizes_arg || sizes_arg[0] == ',' || sizes_arg[strlen(sizes_arg)-1] == ',' || strstr(sizes_arg, ",,")) {
        fputs("invalid size list\n", stderr); return 2;
    }
    char *sizes = strdup(sizes_arg), *save = NULL;
    if (!sizes) return 1;
    unsigned values[16], count = 0;
    for (char *s = strtok_r(sizes, ",", &save); s; s = strtok_r(NULL, ",", &save)) {
        if (count == 16) { fputs("at most16 sizes\n", stderr); return 2; }
        values[count++] = number(s, 1, 128 * 1024);
    }
    free(sizes);
    struct buffer eviction = allocate((size_t)evict_mib * 1048576);
    fill(&eviction, 123);
    puts("# CPU-visible private-buffer rates; first-touch, verification and eviction excluded from timed intervals.");
    puts("# Pressure is not guaranteed cold. No privileged cache flush, MMIO, fixed-address RAM or DDR-peak claim.");
    puts("# Write includes pattern arithmetic; writeback tail is not explicitly drained.");
    for (unsigned i = 0; i < count; i++) {
        if (strcmp(modes, "pressure")) run_size((size_t)values[i] * 1024, repeats, 0, &eviction);
        if (strcmp(modes, "warmed")) run_size((size_t)values[i] * 1024, repeats, 1, &eviction);
    }
    free(eviction.base);
    puts("MEM_BENCH_PASS");
    return 0;
}
