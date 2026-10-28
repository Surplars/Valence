#include "coremark.h"
#include <stdarg.h>
#ifndef BENCH_SEED
#define BENCH_SEED 0
#endif
volatile ee_s32 seed1_volatile=BENCH_SEED, seed2_volatile=BENCH_SEED;
volatile ee_s32 seed3_volatile=0x66, seed4_volatile=1, seed5_volatile=0;
ee_u32 default_num_contexts=1;
volatile uint64_t bench_errors=0, bench_crc_pack=0, bench_iterations=0, bench_final=0, bench_fields=0;
CORE_TICKS get_time(void){return 1;}
secs_ret time_in_secs(CORE_TICKS ticks){(void)ticks;return 0;}
void portable_init(core_portable*p,int*argc,char*argv[]){(void)argc;(void)argv;p->portable_id=1;}
void portable_fini(core_portable*p){p->portable_id=0;}
static int eq(const char*a,const char*b){while(*a&&*a==*b){a++;b++;}return *a==*b;}
static int contains(const char*a,const char*b){for(;*a;a++){const char*x=a,*y=b;while(*x&&*x==*y){x++;y++;}if(!*y)return 1;}return 0;}
int ee_printf(const char*fmt,...){
 va_list ap;va_start(ap,fmt);
 if(eq(fmt,"seedcrc          : 0x%04x\n")){bench_crc_pack|=(uint16_t)va_arg(ap,int);bench_fields|=1;}
 else if(eq(fmt,"[%d]crclist       : 0x%04x\n")){int n=va_arg(ap,int);if(n)bench_errors++;bench_crc_pack|=(uint64_t)(uint16_t)va_arg(ap,int)<<16;bench_fields|=2;}
 else if(eq(fmt,"[%d]crcmatrix     : 0x%04x\n")){int n=va_arg(ap,int);if(n)bench_errors++;bench_crc_pack|=(uint64_t)(uint16_t)va_arg(ap,int)<<32;bench_fields|=4;}
 else if(eq(fmt,"[%d]crcstate      : 0x%04x\n")){int n=va_arg(ap,int);if(n)bench_errors++;bench_crc_pack|=(uint64_t)(uint16_t)va_arg(ap,int)<<48;bench_fields|=8;}
 else if(eq(fmt,"[%d]crcfinal      : 0x%04x\n")){int n=va_arg(ap,int);if(n)bench_errors++;bench_final=(uint16_t)va_arg(ap,int);bench_fields|=16;}
 else if(eq(fmt,"Iterations       : %lu\n")){bench_iterations=va_arg(ap,unsigned long);bench_fields|=32;}
 else if(contains(fmt,"ERROR")&&!eq(fmt,"ERROR! Must execute for at least 10 secs for a valid result!\n")){bench_errors++;}
 else if(contains(fmt,"Cannot validate")){bench_errors++;}
 va_end(ap);return 0;
}
void*memset(void*d,int c,size_t n){unsigned char*p=d;while(n--)*p++=(unsigned char)c;return d;}
void*memcpy(void*d,const void*s,size_t n){unsigned char*p=d;const unsigned char*q=s;while(n--)*p++=*q++;return d;}
