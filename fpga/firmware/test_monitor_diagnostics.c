#define DIAGNOSTIC_TEST 1
#define BOOT_MENU 1
#define BOARD_RAM_BYTES 0x80000000UL
#define BOARD_MONITOR_BASE 0xffff8000UL
#define CPU_HZ 1000ULL
#define main diagnostic_entry_unused
#include "monitor_diagnostics.c"
#undef main
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
static uint64_t source[16384],destination[16384],regs[5],ticks;
static unsigned starts,clears,flushes,fault,reads;
unsigned diagnostic_test_drop_read,diagnostic_test_drop_write;
static char text[8192];static unsigned text_n;
volatile ee_s32 seed4_volatile;
int coremark_main(void){assert(0);return 0;}
int mmu_diagnostic(void){assert(0);return 1;}
volatile uint64_t *diagnostic_test_a(void){return source;}
volatile uint64_t *diagnostic_test_b(void){return destination;}
uint64_t diagnostic_test_tick(void){return ++ticks;}
void diagnostic_test_flush(void){++flushes;}
int ee_printf(const char *fmt,...){va_list ap;va_start(ap,fmt);int n=vsnprintf(text+text_n,sizeof text-text_n,fmt,ap);va_end(ap);assert(n>=0&&(unsigned)n<sizeof text-text_n);text_n+=(unsigned)n;return n;}
uint64_t diagnostic_test_read(unsigned r){assert(r==4);++reads;return regs[r];}
void diagnostic_test_write(unsigned r,uint64_t v){assert(r<4&&!(regs[4]&1));if(r!=3){regs[r]=v;return;}if(v==2){++clears;regs[4]=0;return;}assert(v==3);++starts;
 assert(regs[0]==(uintptr_t)source&&regs[1]==(uintptr_t)destination);assert(regs[2]==512||regs[2]==131072);
 if(fault==1){regs[4]=4|2;return;}if(fault==2){regs[4]=0;return;}if(fault==3){regs[4]=1;return;}
 for(unsigned i=0;i<regs[2]/8;i++)destination[i]=source[i];if(fault==4)destination[17]^=1;regs[4]=2;
}
static void reset(unsigned f){memset(regs,0,sizeof regs);memset(destination,0xa5,sizeof destination);ticks=starts=clears=flushes=reads=text_n=0;text[0]=0;fault=f;diagnostic_short=0;diagnostic_test_drop_read=diagnostic_test_drop_write=0;}
int main(void){unsigned cases=0;
 reset(0);assert(cpu_bandwidth(1));assert(strstr(text,"CPU_BANDWIDTH_PASS"));++cases;
 reset(0);assert(cpu_bandwidth(0));assert(strstr(text,"read_over_cache")&&strstr(text,"read_cache_hot"));++cases;
 for(unsigned quick=0;quick<2;quick++){reset(0);assert(dma_bandwidth(quick));assert(starts==1&&clears==1&&flushes==2);assert(strstr(text,"MEMORY_DMA_PASS"));++cases;}
 for(unsigned f=1;f<=4;f++){reset(f);assert(!dma_bandwidth(1));assert(starts==1&&clears==0);assert(!strstr(text,"MEMORY_DMA_PASS"));if(f==3){assert(regs[4]&1);unsigned old=starts;assert(!dma_bandwidth(1)&&starts==old);}++cases;}
 reset(0);regs[4]=1;assert(!dma_bandwidth(1)&&starts==0&&flushes==0);++cases;
 reset(0);diagnostic_test_drop_write=1;assert(!cpu_bandwidth(1)&&strstr(text,"CPU WRITE FAIL"));++cases;
 reset(0);diagnostic_test_drop_read=1;assert(!cpu_bandwidth(1)&&strstr(text,"CPU READ FAIL"));++cases;
 printf("MONITOR_DIAGNOSTIC_SOFTWARE_PASS cases=%u real_kernel=1 fake_mmio=1 dma_busy_error_missing_done_timeout_corruption=1 no_hardware_claim=1\n",cases);return 0;
}
