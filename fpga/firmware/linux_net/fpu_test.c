#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/auxv.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern void fp_context_roundtrip(const uint64_t *, uint64_t *, unsigned);
static int errors;
#define CHECK(expr) do { if (!(expr)) { printf("FAIL: %s\n", #expr); errors++; } } while (0)
static uint64_t ticks(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) abort();
    return (uint64_t)ts.tv_sec * 1000000000ULL + ts.tv_nsec;
}
static void arithmetic(void)
{
    float a = 1.5f, b = 2.25f, s, three_s = 9.0f;
    double x = 1.5, y = 2.25, d, three_d = 9.0;
    long integer;
    __asm__ volatile("fadd.s %0,%1,%2" : "=f"(s) : "f"(a), "f"(b)); CHECK(s == 3.75f);
    __asm__ volatile("fsub.s %0,%1,%2" : "=f"(s) : "f"(b), "f"(a)); CHECK(s == 0.75f);
    __asm__ volatile("fmul.s %0,%1,%2" : "=f"(s) : "f"(a), "f"(b)); CHECK(s == 3.375f);
    __asm__ volatile("fdiv.s %0,%1,%2,rne" : "=f"(s) : "f"(b), "f"(a)); CHECK(s == 1.5f);
    __asm__ volatile("fsqrt.s %0,%1,rne" : "=f"(s) : "f"(three_s)); CHECK(s == 3.0f);
    __asm__ volatile("fmadd.s %0,%1,%2,%1,rne" : "=f"(s) : "f"(a), "f"(b)); CHECK(s == 4.875f);
    __asm__ volatile("fadd.d %0,%1,%2" : "=f"(d) : "f"(x), "f"(y)); CHECK(d == 3.75);
    __asm__ volatile("fsub.d %0,%1,%2" : "=f"(d) : "f"(y), "f"(x)); CHECK(d == 0.75);
    __asm__ volatile("fmul.d %0,%1,%2" : "=f"(d) : "f"(x), "f"(y)); CHECK(d == 3.375);
    __asm__ volatile("fdiv.d %0,%1,%2,rne" : "=f"(d) : "f"(y), "f"(x)); CHECK(d == 1.5);
    __asm__ volatile("fsqrt.d %0,%1,rne" : "=f"(d) : "f"(three_d)); CHECK(d == 3.0);
    __asm__ volatile("fmadd.d %0,%1,%2,%1,rne" : "=f"(d) : "f"(x), "f"(y)); CHECK(d == 4.875);
    __asm__ volatile("fcvt.l.d %0,%1,rtz" : "=r"(integer) : "f"(y)); CHECK(integer == 2);
    __asm__ volatile("fcvt.d.l %0,%1,rne" : "=f"(d) : "r"(17L)); CHECK(d == 17.0);
    puts(errors ? "F/D ARITHMETIC FAIL" : "F/D ARITHMETIC PASS (S+D add/sub/mul/div/sqrt/fma/convert)");
}
static int context_child(unsigned child)
{
    uint64_t image[32], result[33];
    for (unsigned i = 0; i < 32; i++)
        image[i] = 0x3ff0000000000000ULL + ((uint64_t)child << 40) + i * 0x10203ULL;
    unsigned fcsr = (child ? 3u : 2u) << 5; /* distinct RUP/RDN */
    for (unsigned round = 0; round < 200; round++) {
        memset(result, 0, sizeof(result));
        fp_context_roundtrip(image, result, fcsr); /* 32 FPR + timed blocking syscall */
        if (memcmp(image, result, sizeof(image)) || result[32] != fcsr)
            return 1;
    }
    return 0;
}
static void context(void)
{
    pid_t children[2];
    int before = errors;
    fflush(NULL);
    for (unsigned child = 0; child < 2; child++) {
        children[child] = fork();
        if (!children[child]) _exit(context_child(child));
        if (children[child] < 0) { perror("fork"); errors++; }
    }
    for (unsigned child = 0; child < 2; child++) {
        if (children[child] < 0) continue;
        int status;
        if (waitpid(children[child], &status, 0) != children[child] ||
            !WIFEXITED(status) || WEXITSTATUS(status)) errors++;
    }
    puts(errors == before ? "LINUX FP CONTEXT PASS (2 processes, 32 FPR+FCSR, 400 blocking switches)" :
                           "LINUX FP CONTEXT FAIL");
}
static volatile float af[256], bf[256], sinkf;
static volatile double ad[256], bd[256], sinkd;
static void benchmark(void)
{
    for (unsigned i = 0; i < 256; i++) {
        af[i] = ad[i] = (i % 8 + 1) / 8.0;
        bf[i] = bd[i] = 0.125;
    }
    uint64_t begin = ticks();
    for (unsigned r = 0; r < 10000; r++) {
        float sum = 0;
        for (unsigned i = 0; i < 256; i++) sum += af[i] * bf[i];
        sinkf = sum;
    }
    uint64_t sf = ticks() - begin;
    begin = ticks();
    for (unsigned r = 0; r < 10000; r++) {
        double sum = 0;
        for (unsigned i = 0; i < 256; i++) sum += ad[i] * bd[i];
        sinkd = sum;
    }
    uint64_t sd = ticks() - begin;
    CHECK(sinkf == 18.0f && sinkd == 18.0);
    printf("FPU DOT FP32: %.6f s, %.3f MFLOP/s\n", sf / 1e9, 5120000000.0 / sf);
    printf("FPU DOT FP64: %.6f s, %.3f MFLOP/s\n", sd / 1e9, 5120000000.0 / sd);
    puts("Scalar dependent dot-product + load costs; NOT FPU peak throughput or CoreMark.");
}
int main(int argc, char **argv)
{
    puts("Valence Linux RV64GC/lp64d FPU test V0.1");
    unsigned long hwcap = getauxval(AT_HWCAP);
    const unsigned long fd = (1UL << ('f' - 'a')) | (1UL << ('d' - 'a'));
    printf("Linux AT_HWCAP=0x%lx F=%u D=%u\n", hwcap,
           (unsigned)((hwcap >> ('f' - 'a')) & 1),
           (unsigned)((hwcap >> ('d' - 'a')) & 1));
    if ((hwcap & fd) != fd) {
        puts("FPU TEST FAIL: Linux did not discover both F and D; fix DT/kernel ISA discovery.");
        return 1;
    }
    arithmetic();
    context();
    if (argc > 1 && !strcmp(argv[1], "--bench")) benchmark();
    printf("FPU TEST %s errors=%d\n", errors ? "FAIL" : "PASS", errors);
    return errors ? 1 : 0;
}
