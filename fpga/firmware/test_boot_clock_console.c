#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define BOOT_MENU 1
#define BOARD_CMU_CLOCKS 1
#define BOOTROM_TEST 1
#define TIMEBASE_HZ 250000000ULL
static const char *input;static char output[16384];static unsigned used,writes;
static uint64_t banks[2][16];
static int getc_timeout(uint64_t timeout){(void)timeout;return *input?(unsigned char)*input++:-1;}
static void putc_uart(uint8_t c){assert(used+1<sizeof output);output[used++]=(char)c;output[used]=0;}
static void puts_uart(const char *s){while(*s)putc_uart((uint8_t)*s++);}
static void hex64(uint64_t n){char b[17];snprintf(b,sizeof b,"%016llx",(unsigned long long)n);puts_uart(b);}
static void flush_uart(void){}
static int monitor_quiet(void){return 1;}
#include "boot_clock_console.h"
uint64_t boot_clock_test_read(uint64_t a) {
    if(a>=VALENCE_PERF_CPU)return 0; /* no measurement, not fake configured Hz */
    unsigned d=a>=VALENCE_RATE_FABRIC,off=(unsigned)(a-(d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU))/8;
    return banks[d][off];
}
void boot_clock_test_write(uint64_t a,uint64_t v) {
    ++writes;unsigned d=a>=VALENCE_RATE_FABRIC,off=(unsigned)(a-(d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU))/8;
    banks[d][off]=v;
    if(off==RATE_REQUEST/8){banks[d][RATE_CONFIGURED/8]=v;banks[d][RATE_COMPLETED/8]++;banks[d][RATE_STATUS/8]=RATE_PRESENT|RATE_VALID|RATE_SUCCESS;}
}
int main(void) {
    for(unsigned d=0;d<2;d++) {
        banks[d][RATE_ID/8]=UINT64_C(0x4352000300000002);
        banks[d][RATE_ADMISSION/8]=0x30;banks[d][RATE_CAPS/8]=UINT64_C(0x000080033e200a0a);banks[d][RATE_REFERENCE/8]=250000000;
        banks[d][RATE_STATUS/8]=RATE_PRESENT|RATE_VALID;
        banks[d][RATE_MIN/8]=10000000;banks[d][RATE_MAX/8]=d?250000000:300000000;
    }
    input="list\rcpu 75\rfabric 100\rperf\rquit\r";clock_console();
    assert(writes==4 && banks[0][RATE_CONFIGURED/8]==75000000 && banks[1][RATE_CONFIGURED/8]==100000000);
    assert(strstr(output,"refill_lines") && strstr(output,"64B data line grants"));
    assert(strstr(output,"NOT measured") && strstr(output,"telemetry unavailable") && strstr(output,"completed"));
    writes=0;input="cpu 151\rcpu 9999999999999\rfabric 150extra\rquit\r";clock_console();assert(!writes);
    input="cpu 100abcdefghijklmnopqrstuvwxyz\rquit\r";clock_console();assert(!writes);
    input="\033";clock_console();assert(!writes);
    puts("BOOT_CLOCK_CONSOLE_PASS cpu fabric validation overflow unavailable exit no_auto_change");
}
