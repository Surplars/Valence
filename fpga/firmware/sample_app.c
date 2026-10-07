#include <stdint.h>
static volatile uint64_t check_bss;
static uint64_t initialized = 0x123456789abcdef0ULL;
#ifdef BOARD_DDR
static int ddr_test(void) {
    const uintptr_t addresses[] = {0x80400000UL, 0x90000000UL, 0xa01f7f80UL};
    for (unsigned i = 0; i < 3; ++i) {
        volatile uint64_t *p = (volatile uint64_t *)addresses[i];
        *p = 0x1122334455667788ULL;
        ((volatile uint8_t *)p)[1] = 0xaa;
        ((volatile uint16_t *)p)[2] = 0xbbcc;
        ((volatile uint32_t *)p)[0] = 0x12345678;
        if (*p != 0x1122bbcc12345678ULL) return 0;
        uint64_t old, status, next = 0xabcdeffedcba0123ULL;
        __asm__ volatile (".option push\n.option arch,+a\nlr.d %0,(%2)\nsc.d %1,%3,(%2)\n.option pop"
            : "=&r"(old), "=&r"(status) : "r"(p), "r"(next) : "memory");
        if (old != 0x1122bbcc12345678ULL || status != 0 || *p != next) return 0;
        uint64_t increment = 5;
        __asm__ volatile (".option push\n.option arch,+a\namoadd.d %0,%2,(%1)\n.option pop"
            : "=&r"(old) : "r"(p), "r"(increment) : "memory");
        if (old != next || *p != next + increment) return 0;
    }
    __asm__ volatile ("fence rw,rw" ::: "memory");
    return 1;
}
#endif
int main(void) {
    volatile uint8_t *uart = (volatile uint8_t *)0x10000000UL;
    const char *text = check_bss == 0 && initialized == 0x123456789abcdef0ULL ?
                      "RAM APP OK\r\n" : "RAM APP FAIL\r\n";
#ifdef BOARD_DDR
    if (!ddr_test()) text = "RAM APP FAIL\r\n";
#endif
    check_bss = 1;
    initialized ^= 1;
    while (*text) {
        while (!(uart[5] & 0x20)) {}
        uart[0] = *text++;
    }
    return 0;
}
