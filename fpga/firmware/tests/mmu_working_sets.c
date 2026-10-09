/* Representative target execution: production kernel/counts, 18 READ + 6 stream WRITE/COPY.
 * No UART, no bandwidth promotion, and no claim that all 54 production rows ran. */
#include "../mmu_diagnostic.c"
#define RANGE_CONTROL ((volatile uint64_t *)(DIAG_BASE+0x64000UL))
#define RECORDS ((volatile uint64_t *)(DIAG_BASE+0x65000UL))
static volatile uint64_t *const signature=(volatile uint64_t *)(DIAG_BASE+0x7f000UL);
int ee_printf(const char *format,...){(void)format;return 0;}
__attribute__((noinline,noreturn)) static void stop(unsigned failure,unsigned cases){
    signature[0]=0x4d4d55574f524b53ULL;signature[1]=failure;signature[2]=cases;flush();
    __asm__ volatile(".global mmu_worksets_done\nmmu_worksets_done:\nnop":::"memory");
    for(;;)__asm__ volatile("nop");
}
__attribute__((noinline)) static void case_marker(void){
    __asm__ volatile(".global mmu_worksets_case_done\nmmu_worksets_case_done:\nnop":::"memory");
}
static void initialize(volatile uint64_t *a,volatile uint64_t *b,unsigned op){
    for(uint64_t w=0;w<MMU_WORDS;w++){a[w]=op==1?~pattern(w):pattern(w);b[w]=~pattern(w);}
}
static void one(struct mmu_run *r,unsigned mode,unsigned test,unsigned op,unsigned cases){
    unsigned pages=test<2?0:4U<<(test-2);
    r->count=pages?pages:test?MMU_WORDS:1024;r->passes=pages?128:test?1:8;
    r->sweep=pages!=0;r->operation=op;
    r->source=(volatile uint64_t *)(mode?MMU_VA_A:MMU_A);
    r->destination=(volatile uint64_t *)(mode?MMU_VA_B:MMU_B);
    r->satp=mode?MMU_SV39|(MMU_TABLE_BASE>>12):0;r->stack=MMU_STACK_TOP;
    initialize((volatile uint64_t *)MMU_A,(volatile uint64_t *)MMU_B,op);
    build_tables((volatile uint64_t *)MMU_TABLE_BASE,DIAG_BASE,mode==2);flush();
    unsigned invoked=invoke(r,0);
    signature[3]=r->cause;signature[4]=r->tval;signature[5]=r->epc;
    if(!invoked||!normal(r)||!r->ticks)stop(0x100+cases,cases);
    if(!verify(r,(volatile uint64_t *)MMU_A,(volatile uint64_t *)MMU_B))stop(0x200+cases,cases);
    volatile uint64_t *record=RECORDS+cases*8;
    record[0]=mode;record[1]=test;record[2]=op;record[3]=r->count;
    record[4]=r->passes;record[5]=r->ticks;record[6]=r->tail;record[7]=r->sum;
    case_marker();
}
int main(void){
    struct mmu_run r; /* selfcheck/invoke initialize every consumed field. */unsigned cases=0;
    uint64_t begin=RANGE_CONTROL[0],end=RANGE_CONTROL[1];
    if(begin>=end||end>24)stop(2,0);
    unsigned first=(unsigned)begin,last=(unsigned)end;
    signature[0]=0;signature[1]=~0ULL;signature[2]=0;signature[6]=first;signature[7]=last;
    if(first>=last||last>24)stop(2,0);
    if(!selfcheck(&r,(volatile uint64_t *)MMU_TABLE_BASE))stop(1,0);
    /* Match the menu's per-case full initialization, mapping, warmup, counts,
     * passes and verification. Only row selection/output differs. */
    for(unsigned c=first;c<last;c++){
        unsigned mode=c<18?c/6:(c-18)/2,test=c<18?c%6:1,op=c<18?0:1+(c-18)%2;
        one(&r,mode,test,op,c);++cases;
    }
    stop(0,cases);
}
