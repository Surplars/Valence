/* Separate -O3 RAM-resident kernels. Monitor/ownership driver remains -Os. */
#include <stdint.h>
#include "board_memory.h"
#include "coremark.h"
extern int coremark_main(void);
extern volatile ee_s32 seed4_volatile;
unsigned diagnostic_short;
#ifdef DIAGNOSTIC_TEST
extern volatile uint64_t *diagnostic_test_a(void),*diagnostic_test_b(void);
extern unsigned diagnostic_test_drop_read,diagnostic_test_drop_write;
extern uint64_t diagnostic_test_tick(void),diagnostic_test_read(unsigned);
extern void diagnostic_test_write(unsigned,uint64_t),diagnostic_test_flush(void);
#define A diagnostic_test_a()
#define B diagnostic_test_b()
#else
#define A ((volatile uint64_t *)(DIAG_BASE+0x20000UL))
#define B ((volatile uint64_t *)(DIAG_BASE+0x40000UL))
#define DMA ((volatile uint64_t *)0x10001000UL)
#endif
static volatile uint64_t observed;
#ifdef DIAGNOSTIC_TEST
static uint64_t tick(void){return diagnostic_test_tick();}
static void flush(void){diagnostic_test_flush();}
static uint64_t dma_read(unsigned r){return diagnostic_test_read(r);}
static void dma_write(unsigned r,uint64_t v){diagnostic_test_write(r,v);}
static void io_fence(void){}
#else
static uint64_t dma_read(unsigned r){return DMA[r];}
static void dma_write(unsigned r,uint64_t v){DMA[r]=v;}
static void io_fence(void){__asm__ volatile("fence iorw,iorw":::"memory");}
static uint64_t tick(void){uint64_t t;__asm__ volatile("fence rw,rw\nrdtime %0":"=r"(t)::"memory");return t;}
static void flush(void){__asm__ volatile("fence rw,rw\nfence.i\nfence rw,rw":::"memory");}
#endif
static uint64_t pattern(unsigned i){return 0x935b76124aedc087ULL ^ ((uint64_t)i*0x102040810204081ULL);}
static int verify(unsigned words,unsigned target){for(unsigned i=0;i<words;i++)if((target?B[i]:A[i])!=pattern(i))return 0;return 1;}
static void report(const char *kind,unsigned bytes,uint64_t elapsed,uint64_t tail){
 if(diagnostic_short){ee_printf("SELFTEST %s bytes=%lu ticks=%lu flush_tail=%lu\n",kind,(unsigned long)bytes,(unsigned long)elapsed,(unsigned long)tail);return;}
 ee_printf("BW %s bytes=%lu ticks=%lu flush_tail=%lu clock_hz=%lu milli_MiB_s=%lu\n",kind,(unsigned long)bytes,(unsigned long)elapsed,(unsigned long)tail,(unsigned long)CPU_HZ,(unsigned long)(elapsed?((uint64_t)bytes*CPU_HZ*1000ULL/elapsed)/1048576ULL:0));
}
static uint64_t read_sum(unsigned words) {
    uint64_t sum=0;
    for(unsigned i=0;i<words;i++) {
#ifdef DIAGNOSTIC_TEST
        if(diagnostic_test_drop_read)continue;
#endif
        sum+=A[i];
    }
    return sum;
}
static int cpu_bandwidth(unsigned quick) {
    const unsigned sizes[]={quick?512:8192,quick?4096:131072};
    for(unsigned s=0;s<2;s++) {
        unsigned bytes=sizes[s],words=bytes/8;uint64_t expected=0;
        for(unsigned i=0;i<words;i++){A[i]=pattern(i);B[i]=0;expected+=pattern(i);}
        flush();uint64_t start=tick(),sum=read_sum(words),end=tick();observed=sum;
        if(sum!=expected){ee_printf("CPU READ FAIL\n");return 0;}
        report(quick?"read_short_selftest":s?"read_over_cache":"read_cache_sized_cold",bytes,end-start,0);
        if(!s){start=tick();sum=read_sum(words);end=tick();observed=sum;
            if(sum!=expected){ee_printf("CPU READ FAIL\n");return 0;}
            report(quick?"read_short_hot":"read_cache_hot",bytes,end-start,0);}
        /* Untimed contrasting data makes every measured write observable. */
        for(unsigned i=0;i<words;i++)A[i]=~pattern(i);
        start=tick();
        for(unsigned i=0;i<words;i++) {
#ifdef DIAGNOSTIC_TEST
            if(diagnostic_test_drop_write)continue;
#endif
            A[i]=pattern(i);
        }
        end=tick();flush();uint64_t done=tick();
        if(!verify(words,0)){ee_printf("CPU WRITE FAIL\n");return 0;}
        report(quick?"write_short_selftest":s?"write_over_cache":"write_cache_sized",bytes,end-start,done-end);
        start=tick();for(unsigned i=0;i<words;i++)B[i]=A[i];end=tick();flush();done=tick();
        if(!verify(words,1)){ee_printf("CPU COPY FAIL\n");return 0;}
        report(quick?"copy_short_selftest":s?"copy_over_cache":"copy_cache_sized",bytes,end-start,done-end);
    }
    ee_printf("CPU_BANDWIDTH_PASS verified=1 copy_bytes=payload_not_double_bus_traffic\n");return 1;
}
static int dma_bandwidth(unsigned quick){
 const unsigned bytes=quick?512:131072,words=bytes/8;
 if(dma_read(4)&1){ee_printf("DMA BUSY; RESET REQUIRED\n");return 0;}
 for(unsigned i=0;i<words;i++){A[i]=pattern(i);B[i]=0;}
 flush();
 dma_write(0,(uintptr_t)A);dma_write(1,(uintptr_t)B);dma_write(2,bytes);
 io_fence();
 uint64_t start=tick();dma_write(3,3);
 uint64_t status;
 do {status=dma_read(4);if(tick()-start>CPU_HZ*2ULL){ee_printf("DMA TIMEOUT; buffers pinned, RESET REQUIRED\n");return 0;}}while(status&1);
 io_fence();uint64_t end=tick();
 if((status&6)!=2){ee_printf("DMA ERROR status=%lu\n",(unsigned long)status);return 0;}
 flush();uint64_t settled=tick();
 if(!verify(words,1)){ee_printf("DMA DATA FAIL\n");return 0;}
 dma_write(3,2);report("memory_dma_copy",bytes,end-start,settled-end);
 ee_printf("MEMORY_DMA_PASS true_mem2mem=1 verified=1 completion_includes_write_responses=1\n");return 1;
}
int main(void){
 unsigned op=*(volatile uint64_t *)(DIAG_BASE+0x7ff00UL);
 ee_printf("DIAG code=RAM flags=-O3 ISA=rv64im_zicsr_zifencei clock_hz=%lu\n",(unsigned long)CPU_HZ);
 if(op=='c'||op=='C'){
  diagnostic_short=op=='c';seed4_volatile=diagnostic_short?1:0;
  ee_printf(diagnostic_short?"COREMARK SHORT CRC SELFTEST; NOT A SCORE\n":"COREMARK FORMAL automatic >=10s; use full CRC/result validity\n");
  return coremark_main();
 }
 if(op=='b')return cpu_bandwidth(0)?0:1;
 if(op=='m')return dma_bandwidth(0)?0:1;
 if(op=='t'){diagnostic_short=1;ee_printf("SHORT DIAGNOSTICS SELFTEST; NOT BANDWIDTH SCORE\n");return cpu_bandwidth(1)&&dma_bandwidth(1)?0:1;}
 ee_printf("DIAGNOSTIC COMMAND REJECTED\n");return 1;
}
