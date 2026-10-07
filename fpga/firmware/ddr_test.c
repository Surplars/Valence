#include <stdint.h>
#include <stddef.h>

#ifndef CPU_HZ
#define CPU_HZ 50000000ULL
#endif
#define DDR_BASE 0x80200000UL
#define TEST_FIRST 0x80400000UL
#define TEST_END 0xa01f8000UL /* Exclusive: app stack + BootROM occupy the last 32 KiB. */
#ifndef UART_BAUD
#define UART_BAUD 1500000U
#endif

#define UART ((volatile uint8_t *)0x10000000UL)
static unsigned errors;
static unsigned aborted;

static void putc_uart(char c) {
    while (!(UART[5] & 0x20)) {}
    UART[0] = (uint8_t)c;
}
static void text(const char *s) { while (*s) putc_uart(*s++); }
static void hex(uint64_t v) {
    text("0x");
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned d = (v >> shift) & 15;
        putc_uart(d < 10 ? '0' + d : 'a' + d - 10);
    }
}
static void decimal(uint64_t v) {
    char digits[24];
    unsigned n = 0;
    do { digits[n++] = '0' + v % 10; v /= 10; } while (v);
    while (n) putc_uart(digits[--n]);
}
static uint64_t ticks(void) {
    uint64_t v;
    __asm__ volatile ("rdtime %0" : "=r"(v));
    return v;
}
static int key(void) {
    unsigned status = UART[5];
    return status & 1 ? UART[0] : -1;
}
/* Valence-specific: MachinePlatform connects FENCE.I to dirty L1 writeback/invalidate.
 * FENCE alone, or volatile alone, would not force these accesses to reach DDR.
 * This is NOT a portable RISC-V cache-maintenance contract.
 */
static void sync_ddr(void) {
    __asm__ volatile ("fence rw,rw\nfence.i\nfence rw,rw" ::: "memory");
}
static int check(uintptr_t address, uint64_t expected) {
    uint64_t actual = *(volatile uint64_t *)address;
    if (actual == expected) return 1;
    ++errors;
    if (errors <= 8) {
        text("FAIL addr="); hex(address);
        text(" expected="); hex(expected);
        text(" actual="); hex(actual); text("\r\n");
    }
    return 0;
}
static uint64_t pattern(uintptr_t address, unsigned kind) {
    if (kind == 0) return 0;
    if (kind == 1) return UINT64_MAX;
    if (kind == 2) return 0xaaaaaaaa55555555ULL;
    if (kind == 3) return 0x55555555aaaaaaaaULL;
    uint64_t p = ((uint64_t)address << 32) | (uint32_t)~address;
    return kind == 4 ? p : ~p;
}
static int walking_data(void) {
    text("Data walking-1/0 (64 bits)...\r\n");
    volatile uint64_t *p = (volatile uint64_t *)0x80401000UL;
    for (unsigned i = 0; i < 128; ++i)
        p[i] = i < 64 ? 1ULL << i : ~(1ULL << (i - 64));
    sync_ddr();
    for (unsigned i = 0; i < 128; ++i) {
        check((uintptr_t)&p[i], i < 64 ? 1ULL << i : ~(1ULL << (i - 64)));
        if (errors >= 8) return 0;
    }
    return !errors;
}
static int byte_lanes(void) {
    text("8/16/32-bit stores at low/middle/high DDR...\r\n");
    const uintptr_t bases[] = {0x80402000UL, 0x90000200UL, 0xa01f7e00UL};
    const uint64_t initial = 0x1122334455667788ULL;
    for (unsigned region = 0; region < 3; ++region) {
        for (unsigned width = 1; width <= 4; width *= 2) {
            unsigned lanes = 8 / width;
            volatile uint64_t *p = (volatile uint64_t *)bases[region];
            for (unsigned lane = 0; lane < lanes; ++lane) p[lane] = initial;
            sync_ddr();
            for (unsigned lane = 0; lane < lanes; ++lane) {
                uintptr_t a = (uintptr_t)&p[lane] + lane * width;
                if (width == 1) *(volatile uint8_t *)a = 0xa0 + lane;
                else if (width == 2) *(volatile uint16_t *)a = 0xbc00 + lane;
                else *(volatile uint32_t *)a = 0xdead0000U + lane;
            }
            sync_ddr();
            for (unsigned lane = 0; lane < lanes; ++lane) {
                unsigned shift = lane * width * 8;
                uint64_t mask = ((1ULL << (width * 8)) - 1) << shift;
                uint64_t v = (width == 1 ? 0xa0ULL : width == 2 ? 0xbc00ULL : 0xdead0000ULL) + lane;
                check((uintptr_t)&p[lane], (initial & ~mask) | (v << shift));
                if (errors >= 8) return 0;
            }
        }
    }
    return !errors;
}
static int address_alias(void) {
    text("Address bits 3..28 / far-address alias...\r\n");
    uintptr_t points[28];
    unsigned count = 0;
    /* Two set high bits keep every XOR probe out of the low 2 MiB program area. */
    points[count++] = DDR_BASE + 0x00610000UL;
    for (unsigned bit = 3; bit <= 28; ++bit)
        points[count++] = DDR_BASE + (0x00610000UL ^ (1UL << bit));
    points[count++] = TEST_END - 8;
    for (unsigned kind = 4; kind <= 5; ++kind) {
        for (unsigned i = 0; i < count; ++i) {
            if (points[i] < TEST_FIRST || points[i] >= TEST_END) return 0;
            *(volatile uint64_t *)points[i] = pattern(points[i], kind);
        }
        sync_ddr();
        for (unsigned i = count; i; --i) {
            check(points[i - 1], pattern(points[i - 1], kind));
            if (errors >= 8) return 0;
        }
    }
    return !errors;
}
static int cancelled(void) {
    if (key() == 'x') { aborted = 1; text("ABORTED by user\r\n"); return 1; }
    return 0;
}
static int sweep(uintptr_t first, uintptr_t end, unsigned kind, int progress) {
    if (first < TEST_FIRST || end > TEST_END || first >= end || ((first | end) & 7)) {
        text("FAIL unsafe test bounds\r\n"); ++errors; return 0;
    }
    /* Write the entire region before reading any of it, to expose aliasing. */
    for (uintptr_t a = first; a < end; a += 8) {
        if (progress && !((a - first) & 0x7fffffUL)) {
            text("  write "); decimal((a - first) >> 20); text(" MiB\r\n");
            if (cancelled()) return 0;
        }
        *(volatile uint64_t *)a = pattern(a, kind);
    }
    sync_ddr();
    for (uintptr_t a = first; a < end; a += 8) {
        if (progress && !((a - first) & 0x7fffffUL)) {
            text("  read  "); decimal((a - first) >> 20); text(" MiB\r\n");
            if (cancelled()) return 0;
        }
        check(a, pattern(a, kind));
        if (errors >= 8) return 0;
    }
    return !errors;
}
static int smoke(void) {
    if (!walking_data() || !byte_lanes() || !address_alias()) return 0;
    const uintptr_t bases[] = {TEST_FIRST, 0x90000000UL, TEST_END - 256};
    text("Low/middle/high blocks, all six patterns...\r\n");
    for (unsigned region = 0; region < 3; ++region)
        for (unsigned kind = 0; kind < 6; ++kind)
            if (!sweep(bases[region], bases[region] + 256, kind, 0)) return 0;
    return 1;
}
static int quick(void) {
    if (!smoke()) return 0;
    const uintptr_t bases[] = {TEST_FIRST, 0x81000000UL, 0x84000000UL, 0x88000000UL,
                              0x90000000UL, 0x98000000UL, 0x9f000000UL, TEST_END - 65536};
    for (unsigned region = 0; region < 8; ++region) {
        text("64 KiB window "); hex(bases[region]); text("\r\n");
        for (unsigned kind = 0; kind < 6; ++kind) {
            if (cancelled() || !sweep(bases[region], bases[region] + 65536, kind, 0)) return 0;
        }
    }
    return 1;
}
static int full(void) {
    text("Destructive scan: "); hex(TEST_FIRST); text(".."); hex(TEST_END);
    text(" (end exclusive), two address patterns. May take minutes; x aborts.\r\n");
    for (unsigned kind = 4; kind < 6; ++kind) {
        text("Pass "); decimal(kind - 3); text("/2\r\n");
        if (!sweep(TEST_FIRST, TEST_END, kind, 1)) return 0;
    }
    return 1;
}
static void run_test(char command) {
    errors = aborted = 0;
    uint64_t start = ticks();
    int ok = command == 's' ? smoke() : command == 'q' ? quick() : full();
    uint64_t elapsed = ticks() - start;
    text(command == 's' ? "DDR SMOKE " : command == 'q' ? "DDR QUICK " : "DDR FULL ");
    text(aborted ? "ABORTED" : ok && !errors ? "PASS" : "FAIL");
    text(" errors="); decimal(errors); text(" elapsed_ms="); decimal(elapsed / (CPU_HZ / 1000));
    text("\r\n");
}
int main(void) {
    text("\r\nValence DDR test V0.1 - 512 MiB aperture, CPU ");
    decimal(CPU_HZ / 1000000ULL); text(" MHz\r\n");
    text("Destructive tests; program low 2 MiB and top 32 KiB reserved.\r\n");
    text("UART "); decimal(UART_BAUD); text(" 8N1; uses Valence FENCE.I writeback.\r\n");
    run_test('s');
    for (;;) {
        text("[s] smoke  [q] quick  [f] full scan  [x] return to Bootrom\r\n");
        int c;
        do { c = key(); } while (c != 's' && c != 'q' && c != 'f' && c != 'x');
        if (c == 'x') { sync_ddr(); return 0; }
        run_test(c);
    }
}
