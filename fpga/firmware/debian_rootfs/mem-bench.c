/* CPU-visible streaming bandwidth, not DDR/MIG peak. User-private buffers only. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

static volatile uint64_t sink;

static double seconds(clockid_t clock_id)
{
    struct timespec value;
    if (clock_gettime(clock_id, &value)) { perror("clock_gettime"); exit(1); }
    return (double)value.tv_sec + value.tv_nsec * 1e-9;
}

static unsigned argument(const char *text, unsigned maximum)
{
    char *end;
    errno = 0;
    unsigned long value = strtoul(text, &end, 10);
    if (errno || !*text || *end || value < 1 || value > maximum) {
        fprintf(stderr, "argument must be between 1 and %u\n", maximum);
        exit(2);
    }
    return (unsigned)value;
}

static void report(const char *name, size_t bytes, double wall, double cpu)
{
    if (wall <= 0) { fprintf(stderr, "non-positive timer delta\n"); exit(1); }
    printf("%s bytes=%zu wall=%.6fs cpu=%.6fs payload=%.3f MiB/s",
           name, bytes, wall, cpu, bytes / (1024.0 * 1024.0 * wall));
    if (!strncmp(name, "COPY", 4))
        printf(" logical_R+W=%.3f MiB/s", 2.0 * bytes / (1024.0 * 1024.0 * wall));
    putchar('\n');
    fflush(stdout);
}

int main(int argc, char **argv)
{
    if (argc > 3) { fprintf(stderr, "usage: mem-bench [MiB 1..256] [iterations 1..32]\n"); return 2; }
    unsigned mib = argc > 1 ? argument(argv[1], 256) : 32;
    unsigned repeats = argc > 2 ? argument(argv[2], 32) : 3;
    size_t bytes = (size_t)mib * 1024 * 1024, words = bytes / sizeof(uint64_t);
    void *allocation_a = NULL, *allocation_b = NULL;
    if (posix_memalign(&allocation_a, 64, bytes + 128) ||
        posix_memalign(&allocation_b, 64, bytes + 128)) {
        fprintf(stderr, "buffer allocation failed\n"); free(allocation_a); free(allocation_b); return 1;
    }
    uint64_t *a = allocation_a;
    /* A different cache-line offset reduces gratuitous congruent copy conflicts. */
    uint64_t *b = (uint64_t *)((char *)allocation_b + 64);
    printf("Valence CPU memory benchmark: working_set=%u MiB per buffer, iterations=%u\n", mib, repeats);
    puts("Aligned CPU path; no DMA, cache flush or MMIO. COPY is payload plus logical R+W, not AXI traffic.");
    puts("Compare several sizes with dma-bench; a larger DDR capacity does not imply higher throughput.");
    double start = seconds(CLOCK_MONOTONIC_RAW), cpu_start = seconds(CLOCK_PROCESS_CPUTIME_ID);
    uint64_t expected = 0;
    for (size_t i = 0; i < words; i++) {
        a[i] = i ^ UINT64_C(0x13579bdf2468ace0); b[i] = 0; expected += a[i];
    }
    report("FIRST_TOUCH(two_buffers)", bytes * 2, seconds(CLOCK_MONOTONIC_RAW) - start,
           seconds(CLOCK_PROCESS_CPUTIME_ID) - cpu_start);
    uint64_t sum = 0;
    volatile const uint64_t *reader = a;
    start = seconds(CLOCK_MONOTONIC_RAW); cpu_start = seconds(CLOCK_PROCESS_CPUTIME_ID);
    for (unsigned r = 0; r < repeats; r++)
        for (size_t i = 0; i < words; i += 8)
            sum += reader[i] + reader[i+1] + reader[i+2] + reader[i+3] +
                   reader[i+4] + reader[i+5] + reader[i+6] + reader[i+7];
    sink = sum;
    report("READ64", bytes * repeats, seconds(CLOCK_MONOTONIC_RAW) - start,
           seconds(CLOCK_PROCESS_CPUTIME_ID) - cpu_start);
    if (sum != expected * repeats) { fputs("READ verification failed\n", stderr); return 1; }
    volatile uint64_t *writer = b;
    start = seconds(CLOCK_MONOTONIC_RAW); cpu_start = seconds(CLOCK_PROCESS_CPUTIME_ID);
    for (unsigned r = 0; r < repeats; r++)
        for (size_t i = 0; i < words; i += 8) {
            writer[i] = i; writer[i+1] = i+1; writer[i+2] = i+2; writer[i+3] = i+3;
            writer[i+4] = i+4; writer[i+5] = i+5; writer[i+6] = i+6; writer[i+7] = i+7;
        }
    report("WRITE64", bytes * repeats, seconds(CLOCK_MONOTONIC_RAW) - start,
           seconds(CLOCK_PROCESS_CPUTIME_ID) - cpu_start);
    for (size_t i = 0; i < words; i++)
        if (b[i] != i) { fprintf(stderr, "WRITE verification failed at %zu\n", i); return 1; }
    start = seconds(CLOCK_MONOTONIC_RAW); cpu_start = seconds(CLOCK_PROCESS_CPUTIME_ID);
    for (unsigned r = 0; r < repeats; r++) {
        memcpy(b, a, bytes);
        /* Prevent the compiler from coalescing identical repeated copies. */
        __asm__ volatile("" : : "r"(b) : "memory");
    }
    report("COPY(libc)", bytes * repeats, seconds(CLOCK_MONOTONIC_RAW) - start,
           seconds(CLOCK_PROCESS_CPUTIME_ID) - cpu_start);
    if (memcmp(a, b, bytes)) { fputs("COPY verification failed\n", stderr); return 1; }
    struct rusage usage;
    if (!getrusage(RUSAGE_SELF, &usage))
        printf("faults_minor=%ld major=%ld context_switches_voluntary=%ld involuntary=%ld\n",
               usage.ru_minflt, usage.ru_majflt, usage.ru_nvcsw, usage.ru_nivcsw);
    puts("MEM_BENCH_PASS (writeback tail not explicitly drained; CPU-visible only)");
    free(allocation_a); free(allocation_b);
    return 0;
}
