/* Real S-mode alias-capacity experiment. Production privilege/restore helper;
 * separate register-only loop, not the production bandwidth kernel. */
#define mmu_diagnostic_supervisor mmu_reference_supervisor
#include "../mmu_diagnostic.c"
#undef mmu_diagnostic_supervisor
#define RECORDS ((volatile uint64_t *)(DIAG_BASE+0x65000UL))
static volatile uint64_t *const sig=(volatile uint64_t *)(DIAG_BASE+0x7f000UL);
int ee_printf(const char *format,...){(void)format;return 0;}
__attribute__((noinline,noreturn)) static void stop(unsigned failure,unsigned cases){
    sig[0]=0x414c494153434150ULL;sig[1]=failure;sig[2]=cases;flush();
    __asm__ volatile(".global alias_done\nalias_done:\nnop":::"memory");
    for(;;)__asm__ volatile("nop");
}
__attribute__((noinline)) static void begin_case(void){
    __asm__ volatile(".global alias_case_begin\nalias_case_begin:\nnop":::"memory");
}
__attribute__((noinline)) static void end_case(void){
    __asm__ volatile(".global alias_case_end\nalias_case_end:\nnop":::"memory");
}
int main(void){
    const unsigned pages[]={4,7,8,9,15,16,17,32};struct mmu_run r;
    volatile uint64_t *t=(volatile uint64_t *)MMU_TABLE_BASE,*a=(volatile uint64_t *)MMU_A;
    unsigned cases=0;sig[0]=0;sig[1]=~0ULL;sig[2]=0;
    for(unsigned mode=0;mode<2;mode++)for(unsigned k=0;k<8;k++){
        unsigned n=pages[k];for(unsigned w=0;w<512;w++)a[w]=pattern(w);
        build_tables(t,DIAG_BASE,0);
        /* All 32 read-only, A-set 4KiB leaves point to exactly one PA page. */
        for(unsigned p=0;p<32;p++)t[1024+((MMU_A>>12)&511)+p]=(MMU_A>>2)|0x43ULL;
        r.source=(volatile uint64_t *)(mode?MMU_VA_A:MMU_A);r.count=n;r.passes=64;
        r.sweep=mode?4096:0;r.operation=0;r.satp=mode?MMU_SV39|(MMU_TABLE_BASE>>12):0;r.stack=MMU_STACK_TOP;
        flush();begin_case();
        if(!invoke(&r,0)||!normal(&r)||!r.ticks)stop(0x100+cases,cases);
        end_case();
        if(r.sum!=pattern(0)*n*64)stop(0x200+cases,cases);
        for(unsigned w=0;w<512;w++)if(a[w]!=pattern(w))stop(0x300+cases,cases);
        volatile uint64_t *q=RECORDS+8*cases;
        q[0]=mode;q[1]=n;q[2]=64;q[3]=r.ticks;q[4]=r.sum;q[5]=r.source==(void*)MMU_A?MMU_A:MMU_VA_A;
        q[6]=r.sweep;q[7]=4;++cases;
    }
    stop(0,cases);
}
