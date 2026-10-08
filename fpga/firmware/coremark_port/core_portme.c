#include "coremark.h"
#include "core_portme.h"

#include <stdarg.h>

#ifndef COREMARK_ITERATIONS
#define COREMARK_ITERATIONS 0
#endif

#ifndef CPU_HZ
#define CPU_HZ 40000000ULL
#endif
#define UART ((volatile uint8_t *)0x10000000UL)

volatile ee_s32 seed1_volatile = 0;
volatile ee_s32 seed2_volatile = 0;
volatile ee_s32 seed3_volatile = 0x66;
volatile ee_s32 seed4_volatile = COREMARK_ITERATIONS;
volatile ee_s32 seed5_volatile = 0;
ee_u32 default_num_contexts = 1;

static CORETIMETYPE start_tick;
static CORE_TICKS elapsed_ticks;

static CORETIMETYPE timer_tick(void) {
#ifdef DIAGNOSTIC_PORT_TEST
    extern uint64_t diagnostic_port_test_tick(void);
    return diagnostic_port_test_tick();
#else
    CORETIMETYPE tick;
    /* Board rdtime advances once per CPU clock, including inside downloaded apps. */
    __asm__ volatile ("rdtime %0" : "=r"(tick));
    return tick;
#endif
}

void start_time(void) { start_tick = timer_tick(); }
void stop_time(void) { elapsed_ticks = timer_tick() - start_tick; }
CORE_TICKS get_time(void) { return elapsed_ticks; }
secs_ret time_in_secs(CORE_TICKS ticks) {
    return (secs_ret)ticks / (secs_ret)CPU_HZ;
}

static void uart_putc(char c) {
#ifdef DIAGNOSTIC_PORT_TEST
    extern void diagnostic_port_test_putc(char);
    diagnostic_port_test_putc(c);return;
#else
    if (c == '\n') {
        while (!(UART[5] & 0x20)) {}
        UART[0] = '\r';
    }
    while (!(UART[5] & 0x20)) {}
    UART[0] = (uint8_t)c;
#endif
}

static int emit_char(char c) {
    uart_putc(c);
    return 1;
}

static int emit_string(const char *s) {
    int count = 0;
    if (!s) s = "(null)";
    while (*s) count += emit_char(*s++);
    return count;
}

static int emit_unsigned(uint64_t value, unsigned base, unsigned width, char pad) {
    char digits[32];
    unsigned used = 0;
    int count = 0;
    do {
        unsigned digit = value % base;
        digits[used++] = (char)(digit < 10 ? '0' + digit : 'a' + digit - 10);
        value /= base;
    } while (value);
    while (used < width) {
        count += emit_char(pad);
        --width;
    }
    while (used) count += emit_char(digits[--used]);
    return count;
}

static int emit_signed(int64_t value) {
    if (value >= 0) return emit_unsigned((uint64_t)value, 10, 0, ' ');
    int count = emit_char('-');
    uint64_t magnitude = (uint64_t)(-(value + 1)) + 1;
    return count + emit_unsigned(magnitude, 10, 0, ' ');
}

static int emit_float(double value) {
    int count = 0;
    if (value < 0.0) {
        count += emit_char('-');
        value = -value;
    }
    uint64_t whole = (uint64_t)value;
    uint32_t fraction = (uint32_t)((value - (double)whole) * 1000000.0 + 0.5);
    if (fraction == 1000000) {
        ++whole;
        fraction = 0;
    }
    count += emit_unsigned(whole, 10, 0, ' ');
    count += emit_char('.');
    count += emit_unsigned(fraction, 10, 6, '0');
    return count;
}

/* CoreMark uses %d, %u, %lu, %04x, %s and %f outside its timed region. */
#ifdef MONITOR_DIAGNOSTIC
extern unsigned diagnostic_short;
static unsigned short_crc_seen,short_crc_bad;
static int starts(const char *s,const char *p){while(*p){if(*s++!=*p++)return 0;}return 1;}
#endif
int ee_printf(const char *fmt, ...) {
#ifdef MONITOR_DIAGNOSTIC
    if(diagnostic_short) {
        if(starts(fmt,"Iterations/Sec")||starts(fmt,"CoreMark 1.0"))return 0;
        if(starts(fmt,"ERROR! Must execute"))return emit_string("SHORT runtime: formal >=10s rule intentionally not met; no score.\n");
        if(starts(fmt,"Errors detected"))return 0;
        for(const char *p=fmt;*p;p++)if(starts(p,"ERROR!"))short_crc_bad=1;
        unsigned bit=0,wanted=0;
        if(starts(fmt,"seedcrc")){bit=1;wanted=0xe9f5;}
        if(starts(fmt,"[%d]crclist")){bit=2;wanted=0xe714;}
        if(starts(fmt,"[%d]crcmatrix")){bit=4;wanted=0x1fd7;}
        if(starts(fmt,"[%d]crcstate")){bit=8;wanted=0x8e3a;}
        if(bit){va_list check;va_start(check,fmt);if(bit!=1)(void)va_arg(check,int);
            unsigned value=(unsigned)va_arg(check,int);va_end(check);
            short_crc_seen|=bit;if(value!=wanted)short_crc_bad=1;}
    }
#endif
    va_list args;
    int count = 0;
    va_start(args, fmt);
    while (*fmt) {
        if (*fmt != '%') {
            count += emit_char(*fmt++);
            continue;
        }
        ++fmt;
        if (*fmt == '%') {
            count += emit_char(*fmt++);
            continue;
        }
        char pad = ' ';
        unsigned width = 0;
        if (*fmt == '0') { pad = '0'; ++fmt; }
        while (*fmt >= '0' && *fmt <= '9') {
            width = width * 10 + (unsigned)(*fmt++ - '0');
        }
        int long_arg = 0;
        if (*fmt == 'l') { long_arg = 1; ++fmt; }
        switch (*fmt) {
            case 'd':
            case 'i':
                count += emit_signed(long_arg ? va_arg(args, long) : va_arg(args, int));
                break;
            case 'u':
                count += emit_unsigned(long_arg ? va_arg(args, unsigned long)
                                                : va_arg(args, unsigned int), 10, width, pad);
                break;
            case 'x':
                count += emit_unsigned(long_arg ? va_arg(args, unsigned long)
                                                : va_arg(args, unsigned int), 16, width, pad);
                break;
            case 's':
                count += emit_string(va_arg(args, const char *));
                break;
            case 'c':
                count += emit_char((char)va_arg(args, int));
                break;
            case 'f':
                count += emit_float(va_arg(args, double));
                break;
            default:
                count += emit_char('%');
                if (*fmt) count += emit_char(*fmt);
                break;
        }
        if (*fmt) ++fmt;
    }
    va_end(args);
    return count;
}

void portable_init(core_portable *p, int *argc, char *argv[]) {
    (void)argc;
    (void)argv;
    p->portable_id = 1;
#ifdef MONITOR_DIAGNOSTIC
    short_crc_seen=short_crc_bad=0;
    ee_printf("COUNTERS mcycle=unavailable minstret=unavailable IPC=unavailable; rdtime is timebase only\n");
#endif
    ee_printf("VALENCE CoreMark 2K started; calibration and run may take a while.\n");
}

void portable_fini(core_portable *p) {
    p->portable_id = 0;
#ifdef MONITOR_DIAGNOSTIC
    if(diagnostic_short)ee_printf(short_crc_seen==15&&!short_crc_bad?
        "COREMARK_SHORT_CRC_PASS standard2000=1 score=none\n":
        "COREMARK_SHORT_CRC_FAIL\n");
#endif
}
