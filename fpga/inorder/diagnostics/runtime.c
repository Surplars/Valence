#include "platform.h"
int quiet_output;
volatile uint64_t supervisor_active, trap_cause, trap_pc, trap_value;
void putchar_uart(int c) {
    if (quiet_output) return;
    volatile uint8_t *uart = (volatile uint8_t *)0x10000000UL;
    if (c == '\n') putchar_uart('\r');
    while (!(uart[5] & 0x20)) {}
    uart[0] = (uint8_t)c;
}
int getchar_uart(void) {
    volatile uint8_t *uart = (volatile uint8_t *)0x10000000UL;
    while (!(uart[5] & 1)) {}
    return uart[0];
}
void *memset(void *p, int value, size_t n) {
    unsigned char *d=p; while (n--) *d++=(unsigned char)value; return p;
}
void *memcpy(void *p, const void *q, size_t n) {
    unsigned char *d=p; const unsigned char *s=q; while(n--) *d++=*s++; return p;
}
static void number(uint64_t x, unsigned radix, unsigned width, int zero) {
    char b[65]; unsigned n=0;
    do { b[n++]="0123456789abcdef"[x%radix]; x/=radix; } while(x);
    while(width>n) { putchar_uart(zero?'0':' '); --width; }
    while(n) putchar_uart(b[--n]);
}
void print_ratio(uint64_t numerator, uint64_t denominator, unsigned decimals) {
    if (!denominator) { diag_printf("n/a"); return; }
    number(numerator/denominator,10,0,0);
    if (decimals) putchar_uart('.');
    uint64_t remainder=numerator%denominator;
    while(decimals--) { remainder*=10; putchar_uart('0'+remainder/denominator); remainder%=denominator; }
}
int diag_vprintf(const char *fmt, va_list ap) {
    while (*fmt) {
        if (*fmt!='%') { putchar_uart(*fmt++); continue; }
        ++fmt;
        unsigned width=0; int zero=*fmt=='0', wide=0;
        while(*fmt>='0' && *fmt<='9') width=width*10+(*fmt++-'0');
        while(*fmt=='l') { wide=1; ++fmt; }
        char spec=*fmt++;
        if(spec=='s') { const char *s=va_arg(ap,const char *); while(*s) putchar_uart(*s++); }
        else if(spec=='c') putchar_uart(va_arg(ap,int));
        else if(spec=='%') putchar_uart('%');
        else if(spec=='f') {
            double value=va_arg(ap,double);
            if(value<0) { putchar_uart('-'); value=-value; }
            uint64_t scaled=(uint64_t)(value*1000000.0+0.5);
            number(scaled/1000000,10,0,0); putchar_uart('.'); number(scaled%1000000,10,6,1);
        } else if(spec=='d') {
            int64_t value=wide?va_arg(ap,long):va_arg(ap,int);
            uint64_t magnitude=(uint64_t)value;
            if(value<0) { putchar_uart('-'); magnitude=0-magnitude; }
            number(magnitude,10,width,zero);
        } else if(spec=='u' || spec=='x') {
            uint64_t value=wide?va_arg(ap,unsigned long):va_arg(ap,unsigned int);
            number(value,spec=='x'?16:10,width,zero);
        } else { putchar_uart('%'); putchar_uart(spec); }
    }
    return 0;
}
int diag_printf(const char *fmt, ...) {
    va_list ap; va_start(ap,fmt); int result=diag_vprintf(fmt,ap); va_end(ap); return result;
}
void fatal_trap(uint64_t cause, uint64_t pc, uint64_t value) {
    diag_printf("\nFATAL cause=%lu pc=0x%lx tval=0x%lx; RESET REQUIRED\n",cause,pc,value);
    for(;;) __asm__ volatile("nop");
}
