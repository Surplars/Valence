#ifndef VALENCE_BOOT_CLOCK_CONSOLE_H
#define VALENCE_BOOT_CLOCK_CONSOLE_H
/* Included after monitor_quiet(), UART and formatting helpers. */
#if defined(BOOT_MENU) && BOARD_CMU_CLOCKS
#include "valence_clock.h"
static uint64_t clock_mmio_read(void *unused, uint64_t address) {
    (void)unused;
#ifdef BOOTROM_TEST
    extern uint64_t boot_clock_test_read(uint64_t);
    return boot_clock_test_read(address);
#else
    uint64_t value;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    value=*(volatile uint64_t *)(uintptr_t)address;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    return value;
#endif
}
static void clock_mmio_write(void *unused, uint64_t address, uint64_t value) {
    (void)unused;
#ifdef BOOTROM_TEST
    extern void boot_clock_test_write(uint64_t,uint64_t);
    boot_clock_test_write(address,value);
#else
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    *(volatile uint64_t *)(uintptr_t)address=value;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
#endif
}
static const struct valence_clock_io clock_io={0,clock_mmio_read,clock_mmio_write};
static void clock_field(const char *label,uint64_t value) {
    puts_uart(label);hex64(value);
}
static void clock_status(void) {
    for(unsigned d=0;d<2;++d) {
        uint64_t b=d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU;
        puts_uart(d?"fabric":"cpu");
        clock_field(" ABI=0x",clock_mmio_read(0,b+RATE_ID));
        clock_field(" configured_Hz=0x",clock_mmio_read(0,b+RATE_CONFIGURED));
        clock_field(" status=0x",clock_mmio_read(0,b+RATE_STATUS));
        clock_field(" errors=0x",clock_mmio_read(0,b+RATE_ERRORS));
        clock_field(" admission_flags=0x",clock_mmio_read(0,b+RATE_ADMISSION));
        clock_field(" capabilities=0x",clock_mmio_read(0,b+RATE_CAPS));
        puts_uart("\r\n");
    }
    puts_uart("Configured Hz is NOT measured Hz. Diagnostic admission is NOT timing sign-off.\r\n");
}
static void clock_performance(void) {
    if(!valence_rate_v2(&clock_io,VALENCE_RATE_CPU)) {
        puts_uart("Telemetry unavailable on pre-v2 clock platform\r\n");return;
    }
    for(unsigned d=0;d<2;++d) {
        struct valence_perf_snapshot s;
        puts_uart(d?"fabric":"cpu");
        int rc=valence_perf_read(&clock_io,d?VALENCE_PERF_FABRIC:VALENCE_PERF_CPU,&s,8);
        if(rc){puts_uart(" telemetry unavailable/stale/transition; retry after settle\r\n");continue;}
        clock_field(" measured_Hz=0x",valence_perf_measured_hz(&s));
        clock_field(" sample=0x",s.sequence);clock_field(" window_AON_edges=0x",s.window);
        puts_uart("\r\n delta[0..7]=");
        for(unsigned i=0;i<8;++i){hex64(s.delta[i]);putc_uart(' ');}
        puts_uart("\r\n");
        if(!d && s.delta[0])clock_field(" retire0_per_cycle_x1000=0x",(uint64_t)s.delta[1]*1000/s.delta[0]);
        if(d) {
            clock_field(" accepted_R_beats_per_sec=0x",(uint64_t)s.delta[5]*s.reference_hz/s.window);
            clock_field(" accepted_W_beats_per_sec=0x",(uint64_t)s.delta[6]*s.reference_hz/s.window);
        }
        puts_uart("\r\n");
    }
    puts_uart("CPU: edges, retire0, lane1_requests, Dcache_A, A_stall, refill_lines, refill_stall, no_retire\r\n");
    puts_uart("Fabric: edges, AR, AR_stall, AW, AW_stall, R_beats, W_beats, R_stall\r\n");
    puts_uart("CPU refill_lines: accepted 64B data line grants; refill_stall: backpressured cycles.\r\nI1 single-retire: retire0/cycle is IPC; not generic OoO total IPC.\r\nCounters are window deltas; cache misses/private core stalls unavailable.\r\n");
}
static int clock_equal(const char *a,const char *b) {
    while(*a && *a==*b){++a;++b;}return *a==*b;
}
static void clock_console(void) {
    char line[24];
    puts_uart("CMU: status | list | cpu <MHz> | fabric <MHz> | perf | quit\r\n");
    puts_uart("No automatic overclock. Explicit requests are diagnostic, not board qualification.\r\n");
    clock_status();
    for(;;) {
        unsigned n=0,overflow=0;puts_uart("cmu> ");
        for(;;) {
            int c=getc_timeout(TIMEBASE_HZ*30ULL);
            if(c<0||c==27||c==3){puts_uart("\r\nCMU console closed\r\n");return;}
            if(c=='\n'&&!n)continue;
            if(c=='\r'||c=='\n')break;
            if(c==8||c==127){if(n){--n;puts_uart("\b \b");}continue;}
            if(c<32||c>126)continue;
            if(n+1<sizeof(line)){line[n++]=(char)c;putc_uart((uint8_t)c);}else overflow=1;
        }
        line[n]=0;puts_uart("\r\n");
        if(overflow){puts_uart("Command too long\r\n");continue;}
        if(clock_equal(line,"quit"))return;
        if(clock_equal(line,"status")){clock_status();continue;}
        if(clock_equal(line,"perf")){clock_performance();continue;}
        if(clock_equal(line,"list")) {
            puts_uart("Initial software points (MHz): 50 55 60 65 70 75 80 85 90 95 100 105 110 115 120 125 130 135 140 145 150\r\n");
            puts_uart("Exact integer M/D/O calculated in firmware; HW range/capability governs acceptance.\r\n");continue;
        }
        uint64_t base=0;const char *p=line;
        if(n>4 && line[0]=='c'&&line[1]=='p'&&line[2]=='u'&&line[3]==' '){base=VALENCE_RATE_CPU;p+=4;}
        else if(n>7&&line[0]=='f'&&line[1]=='a'&&line[2]=='b'&&line[3]=='r'&&line[4]=='i'&&line[5]=='c'&&line[6]==' '){base=VALENCE_RATE_FABRIC;p+=7;}
        unsigned mhz=0;
        while(*p>='0'&&*p<='9'&&mhz<=300){mhz=mhz*10+(unsigned)(*p++-'0');}
        if(!base||*p||mhz<50||mhz>150||mhz%5){puts_uart("Use cpu/fabric 50..150 in 5 MHz steps; status/list/perf/quit\r\n");continue;}
        if(!monitor_quiet()){puts_uart("Clock request blocked: DMA not quiet\r\n");continue;}
        flush_uart();
        int rc=valence_rate_set(&clock_io,base,mhz*1000000U,1000000);
        puts_uart(rc==RATE_OK?"Clock request completed\r\n":"Clock request FAILED or timed out; inspect status before retry\r\n");
        clock_field(" result_signed_hex=0x",(uint64_t)(int64_t)rc);puts_uart("\r\n");clock_status();
    }
}
#endif
#endif
