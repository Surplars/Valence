#include "coremark.h"
#include "../linux-syscall.h"
#include <stdarg.h>

ee_u32 default_num_contexts = 1;
static CORE_TICKS started, elapsed;

struct linux_timespec { long seconds, nanoseconds; };

static CORE_TICKS now_ms(void) {
    struct linux_timespec now;
    if (linux_syscall3(113, 1, (long)&now, 0) < 0) return 0; /* CLOCK_MONOTONIC */
    return (CORE_TICKS)now.seconds * 1000 + (CORE_TICKS)now.nanoseconds / 1000000;
}

void start_time(void) { started = now_ms(); }
void stop_time(void) { elapsed = now_ms() - started; }
CORE_TICKS get_time(void) { return elapsed; }
secs_ret time_in_secs(CORE_TICKS ticks) { return (secs_ret)(ticks / 1000); }

void portable_init(core_portable *p, int *argc, char *argv[]) {
    (void)argc; (void)argv;
    p->portable_id = 1;
}
void portable_fini(core_portable *p) { p->portable_id = 0; }

/* CoreMark's no-FPU path only requires strings and integer conversions. */
int ee_printf(const char *fmt, ...) {
    char out[512];
    unsigned used = 0;
    va_list args;
    va_start(args, fmt);
    for (const char *p = fmt; *p && used < sizeof(out) - 24; ++p) {
        if (*p != '%') { out[used++] = *p; continue; }
        ++p;
        if (*p == '%') { out[used++] = '%'; continue; }
        unsigned width = 0;
        char pad = ' ';
        if (*p == '0') { pad = '0'; ++p; }
        while (*p >= '0' && *p <= '9') { width = width * 10 + *p++ - '0'; }
        int is_long = 0;
        if (*p == 'l') { is_long = 1; ++p; }
        if (*p == 's') {
            const char *value = va_arg(args, const char *);
            while (*value && used < sizeof(out)) out[used++] = *value++;
            continue;
        }
        int hex = *p == 'x' || *p == 'X';
        int sign = *p == 'd' || *p == 'i';
        unsigned long value = is_long ? va_arg(args, unsigned long) : va_arg(args, unsigned int);
        char digits[24];
        unsigned count = 0;
        int negative = sign && ((is_long && (long)value < 0) || (!is_long && (int)value < 0));
        if (negative) value = is_long ? (unsigned long)(-(long)value) : (unsigned long)(-(int)value);
        do {
            unsigned digit = value % (hex ? 16 : 10);
            digits[count++] = "0123456789abcdef"[digit];
            value /= hex ? 16 : 10;
        } while (value && count < sizeof(digits));
        if (negative && pad == ' ') digits[count++] = '-';
        unsigned padding = width > count ? width - count : 0;
        while (padding-- && used < sizeof(out)) out[used++] = pad;
        if (negative && pad == '0' && used < sizeof(out)) out[used++] = '-';
        while (count && used < sizeof(out)) out[used++] = digits[--count];
    }
    va_end(args);
    linux_write(out, used);
    return used;
}
