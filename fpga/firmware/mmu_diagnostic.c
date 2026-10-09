/* Boot-only, real S-mode Bare/Sv39 comparison. No printing or MMIO in the ROI. */
#include <stddef.h>
#include <stdint.h>
#include "board_memory.h"
#include "mmu_diagnostic.h"
extern int ee_printf(const char *,...);
_Static_assert(offsetof(struct mmu_run,cause)==MMU_CAUSE,"MMU assembly ABI cause");
_Static_assert(offsetof(struct mmu_run,tval)==MMU_TVAL,"MMU assembly ABI tval");
_Static_assert(offsetof(struct mmu_run,epc)==MMU_EPC,"MMU assembly ABI epc");
_Static_assert(offsetof(struct mmu_run,trap_sp)==MMU_TRAP_SP,"MMU assembly ABI trap_sp");
_Static_assert(offsetof(struct mmu_run,returned)==MMU_RETURN,"MMU assembly ABI returned");
_Static_assert(offsetof(struct mmu_run,satp)==MMU_SATP,"MMU assembly ABI satp");
_Static_assert(offsetof(struct mmu_run,stack)==MMU_STACK,"MMU assembly ABI stack");
#define MMU_TABLE_BASE (DIAG_BASE+0x60000UL)
#define MMU_STACK_BOTTOM (DIAG_BASE+0x70000UL)
#define MMU_STACK_TOP (DIAG_BASE+0x78000UL)
#define MMU_WORDS 16384UL
#define MMU_A (DIAG_BASE+0x20000UL)
#define MMU_B (DIAG_BASE+0x40000UL)
#define MMU_VA_A (0x40000000UL+(MMU_A&0x1fffffUL))
#define MMU_VA_B (0x40200000UL+(MMU_B&0x1fffffUL))
#define MMU_SV39 (8ULL<<60)
#define MMU_AD_RW 0xc7ULL
_Static_assert((MMU_TABLE_BASE&4095)==0,"page table alignment");
_Static_assert(MMU_TABLE_BASE+4*4096<=MMU_STACK_BOTTOM,"page tables overlap S stack");
_Static_assert(MMU_STACK_TOP<=DIAG_BASE+0x7ff00UL,"S stack overlaps mailbox");
_Static_assert((MMU_A&0x1fffffUL)+131072<=0x200000UL,"source huge-page boundary");
_Static_assert((MMU_B&0x1fffffUL)+131072<=0x200000UL,"destination huge-page boundary");
#ifdef MMU_DIAGNOSTIC_TEST
extern uint64_t mmu_test_tick(void);
extern void mmu_test_flush(void);
extern unsigned mmu_test_drop_read,mmu_test_drop_write;
#define tick mmu_test_tick
#define flush mmu_test_flush
#else
static uint64_t tick(void){uint64_t t;__asm__ volatile("fence rw,rw\nrdtime %0":"=r"(t)::"memory");return t;}
static void flush(void){__asm__ volatile("fence rw,rw\nfence.i\nfence rw,rw":::"memory");}
#endif
static uint64_t pattern(uint64_t word){return 0x729ad0513fe68bc4ULL^(word*0x102040810204081ULL);}
/* Offset each page's line: 4-KiB stride alone would alias only four L1 sets. */
static uint64_t selected_word(uint64_t n,uint64_t sweep){return sweep?n*512+n*8:n;}
void mmu_diagnostic_supervisor(struct mmu_run *r){
    volatile uint64_t *a=r->source,*b=r->destination;
    uint64_t count=r->count,passes=r->passes,sweep=r->sweep,op=r->operation,sum=0;
    /* Untimed translation/cache warmup, with the actual operation's R/W keys. */
    for(uint64_t n=0;n<count;n++){
        uint64_t w=selected_word(n,sweep);
        if(op==1)a[w]=~pattern(w);
        else {sum+=a[w];if(op==2)b[w]=~pattern(w);}
    }
    r->sum=sum;sum=0;
    uint64_t begin=tick();
    if(op==0){
        for(uint64_t p=0;p<passes;p++)for(uint64_t n=0;n<count;n++){
#ifdef MMU_DIAGNOSTIC_TEST
            if(mmu_test_drop_read)continue;
#endif
            sum+=a[selected_word(n,sweep)];
        }
    }else if(op==1){
        for(uint64_t p=0;p<passes;p++)for(uint64_t n=0;n<count;n++){
#ifdef MMU_DIAGNOSTIC_TEST
            if(mmu_test_drop_write)continue;
#endif
            uint64_t w=selected_word(n,sweep);a[w]=pattern(w);
        }
    }else{
        for(uint64_t p=0;p<passes;p++)for(uint64_t n=0;n<count;n++){
#ifdef MMU_DIAGNOSTIC_TEST
            if(mmu_test_drop_write)continue;
#endif
            uint64_t w=selected_word(n,sweep);b[w]=a[w];
        }
    }
    uint64_t end=tick();
    if(op){flush();r->tail=tick()-end;}else r->tail=0;
    r->ticks=end-begin;r->sum=sum;
}
static void build_tables(volatile uint64_t *t,uint64_t physical_base,unsigned huge){
    uint64_t pa=physical_base+0x20000, pb=physical_base+0x40000;
    uint64_t table_pa=physical_base+0x60000;
    for(unsigned n=0;n<2048;n++)t[n]=0;
    /* Code, metadata and both stacks keep identity addresses in one 1-GiB leaf. */
    unsigned identity=(unsigned)(physical_base>>30);
    t[identity]=((physical_base&~0x3fffffffULL)>>2)|0xcf;
    t[1]=((table_pa+4096)>>2)|1;
    if(huge){
        t[512]=((pa&~0x1fffffULL)>>2)|MMU_AD_RW;
        t[513]=((pb&~0x1fffffULL)>>2)|MMU_AD_RW;
    }else{
        t[512]=((table_pa+8192)>>2)|1;t[513]=((table_pa+12288)>>2)|1;
        for(unsigned n=0;n<32;n++){
            t[1024+((pa>>12)&511)+n]=((pa+(uint64_t)n*4096)>>2)|MMU_AD_RW;
            t[1536+((pb>>12)&511)+n]=((pb+(uint64_t)n*4096)>>2)|MMU_AD_RW;
        }
    }
}
static int verify(struct mmu_run *r,volatile uint64_t *a,volatile uint64_t *b){
    uint64_t expected=0;
    for(uint64_t n=0;n<r->count;n++)expected+=pattern(selected_word(n,r->sweep));
    if(r->operation==0&&r->sum!=expected*r->passes)return 0;
    for(uint64_t w=0;w<MMU_WORDS;w++){
        unsigned touched= r->sweep ? (w%520==0&&w/520<r->count) : w<r->count;
        uint64_t want=pattern(w),awant=r->operation==1&&!touched?~want:want;
        uint64_t bwant=r->operation==2&&touched?want:~want;
        if(a[w]!=awant||b[w]!=bwant)return 0;
    }
    return 1;
}
static uint64_t reject_context(uint64_t cfg0,uint64_t cfg2,uint64_t satp,uint64_t status){
    return (((cfg0|cfg2)&0x8080808080808080ULL)?1:0)|(satp?2:0)|
        ((status&0x20000)?4:0)|((status&8)?8:0);
}

#ifndef MMU_DIAGNOSTIC_TEST
#define READ_CSR(c) ({uint64_t v;__asm__ volatile("csrr %0," #c:"=r"(v)::"memory");v;})
#define WRITE_CSR(c,v) do{uint64_t x=(v);__asm__ volatile("csrw " #c ",%0"::"r"(x):"memory");}while(0)
struct saved_context {uint64_t status,mie,mtvec,stvec,mscratch,sscratch,medeleg,mideleg,mcounteren,scounteren,satp,mepc,sepc,mcause,mtval,scause,stval,pmpcfg0,pmpcfg2,pmpaddr0,pmpaddr1;};
#define CSRS(X) X(status,mstatus) X(mie,mie) X(mtvec,mtvec) X(stvec,stvec) X(mscratch,mscratch) X(sscratch,sscratch) X(medeleg,medeleg) X(mideleg,mideleg) X(mcounteren,mcounteren) X(scounteren,scounteren) X(satp,satp) X(mepc,mepc) X(sepc,sepc) X(mcause,mcause) X(mtval,mtval) X(scause,scause) X(stval,stval) X(pmpcfg0,pmpcfg0) X(pmpcfg2,pmpcfg2) X(pmpaddr0,pmpaddr0) X(pmpaddr1,pmpaddr1)
static int invoke(struct mmu_run *r,unsigned deny_pmp){
    /* Defined result even when preflight rejects before any CSR mutation. */
    r->cause=~0ULL;r->tval=r->epc=r->trap_sp=r->returned=r->ticks=r->tail=r->sum=0;
    struct saved_context s;uintptr_t sp,gp,sp_after,gp_after;
#define SAVE(field,csr) s.field=READ_CSR(csr);
    CSRS(SAVE)
#undef SAVE
    __asm__ volatile("mv %0,sp\nmv %1,gp":"=r"(sp),"=r"(gp)::"memory");
    /* Never modify an inherited locked region or a caller using translation/MPRV/MIE. BootROM enters with MIE clear. */
    uint64_t rejected=reject_context(s.pmpcfg0,s.pmpcfg2,s.satp,s.status);
    if(rejected){r->tval=rejected;return 0;}
    WRITE_CSR(mie,0);WRITE_CSR(mstatus,s.status&~0x2000aULL);
    WRITE_CSR(medeleg,0);WRITE_CSR(mideleg,0);
    WRITE_CSR(mcounteren,s.mcounteren|2);WRITE_CSR(scounteren,s.scounteren|2);
    WRITE_CSR(pmpcfg0,0);WRITE_CSR(pmpcfg2,0);
    WRITE_CSR(pmpaddr0,RAM_BASE>>2);WRITE_CSR(pmpaddr1,(RAM_BASE+(uint64_t)BOARD_RAM_BYTES)>>2);
    uint64_t grant=deny_pmp?0x0800:0x0f00;
    WRITE_CSR(pmpcfg0,grant); /* entry0 OFF lower bound; entry1 TOR RWX, only RAM. */
    int allowed=READ_CSR(pmpcfg0)==grant&&READ_CSR(pmpaddr0)==(RAM_BASE>>2)&&
        READ_CSR(pmpaddr1)==((RAM_BASE+(uint64_t)BOARD_RAM_BYTES)>>2);
    if(allowed)mmu_diagnostic_enter(r);else r->tval=16;
    WRITE_CSR(mie,0);WRITE_CSR(satp,s.satp);__asm__ volatile("sfence.vma x0,x0":::"memory");
    WRITE_CSR(pmpcfg0,0);WRITE_CSR(pmpcfg2,0);
    WRITE_CSR(pmpaddr0,s.pmpaddr0);WRITE_CSR(pmpaddr1,s.pmpaddr1);
    WRITE_CSR(pmpcfg0,s.pmpcfg0);WRITE_CSR(pmpcfg2,s.pmpcfg2);
    WRITE_CSR(mtvec,s.mtvec);WRITE_CSR(stvec,s.stvec);WRITE_CSR(mscratch,s.mscratch);WRITE_CSR(sscratch,s.sscratch);
    WRITE_CSR(medeleg,s.medeleg);WRITE_CSR(mideleg,s.mideleg);WRITE_CSR(mcounteren,s.mcounteren);WRITE_CSR(scounteren,s.scounteren);
    WRITE_CSR(mepc,s.mepc);WRITE_CSR(sepc,s.sepc);WRITE_CSR(mcause,s.mcause);WRITE_CSR(mtval,s.mtval);WRITE_CSR(scause,s.scause);WRITE_CSR(stval,s.stval);
    WRITE_CSR(mie,s.mie);WRITE_CSR(mstatus,s.status);
    __asm__ volatile("mv %0,sp\nmv %1,gp":"=r"(sp_after),"=r"(gp_after)::"memory");
    int restored=sp==sp_after&&gp==gp_after;
#define CHECK(field,csr) restored=restored&&(READ_CSR(csr)==s.field);
    CSRS(CHECK)
#undef CHECK
    if(!restored){ee_printf("MMU RETURN STATE FAIL; RESET REQUIRED\n");for(;;){}}
    return allowed;
}
static int normal(const struct mmu_run *r){return r->cause==9&&r->epc==(uintptr_t)mmu_diagnostic_return_ecall&&r->trap_sp>=MMU_STACK_BOTTOM&&r->trap_sp<=MMU_STACK_TOP;}
static int selfcheck(struct mmu_run *r,volatile uint64_t *t){
    r->satp=MMU_SV39|(MMU_TABLE_BASE>>12);r->stack=MMU_STACK_TOP;
    r->source=(volatile uint64_t *)0x50000000UL;r->destination=(volatile uint64_t *)MMU_VA_B;
    r->count=r->passes=1;r->sweep=r->operation=0;
    build_tables(t,DIAG_BASE,0);flush();
    if(!invoke(r,0)||r->cause!=13||r->tval!=0x50000000UL)return 0;
    r->source=(volatile uint64_t *)MMU_VA_A;r->operation=1;
    uint64_t before=*(volatile uint64_t *)MMU_A;
    build_tables(t,DIAG_BASE,0);t[1024+((MMU_A>>12)&511)]&=~128ULL;flush();
    if(!invoke(r,0)||r->cause!=15||r->tval!=MMU_VA_A||*(volatile uint64_t *)MMU_A!=before)return 0;
    build_tables(t,DIAG_BASE,0);flush();
    if(!invoke(r,1)||r->cause!=1||r->tval!=(uintptr_t)mmu_diagnostic_supervisor_entry)return 0;
    ee_printf("MMU_TRAP_RESTORE_PASS unmapped_load=13 dirty_clear_store=15 pmp_ptw_fetch=1 real_S_mode=1\n");return 1;
}
int mmu_diagnostic(void){
    volatile uint64_t *a=(volatile uint64_t *)MMU_A,*b=(volatile uint64_t *)MMU_B,*t=(volatile uint64_t *)MMU_TABLE_BASE;
    struct mmu_run r;
    ee_printf("MMU_DIAG S-mode Bare vs Sv39; same kernel/physical buffers; rdtime_hz=%lu\n",(unsigned long)CPU_HZ);
    ee_printf("MMU_SCOPE software timing only; no TLB miss counters; data A/D preset; sweep line offsets avoid same-set alias\n");
    if(!selfcheck(&r,t)){ee_printf("MMU SELFTEST FAIL cause=%lu tval=%lx\n",(unsigned long)r.cause,(unsigned long)r.tval);return 1;}
    for(unsigned mode=0;mode<3;mode++)for(unsigned test=0;test<6;test++)for(unsigned op=0;op<3;op++){
        unsigned pages=test<2?0:4U<<(test-2);
        r.count=pages?pages:test?MMU_WORDS:1024;r.passes=pages?128:test?1:8;r.sweep=pages!=0;r.operation=op;
        r.source=(volatile uint64_t *)(mode?MMU_VA_A:MMU_A);r.destination=(volatile uint64_t *)(mode?MMU_VA_B:MMU_B);
        r.satp=mode?MMU_SV39|(MMU_TABLE_BASE>>12):0;r.stack=MMU_STACK_TOP;
        for(uint64_t w=0;w<MMU_WORDS;w++){a[w]=op==1?~pattern(w):pattern(w);b[w]=~pattern(w);}
        build_tables(t,DIAG_BASE,mode==2);flush();
        if(!invoke(&r,0)||!normal(&r)){ee_printf("MMU RUN FAULT mode=%u op=%u cause=%lu tval=%lx epc=%lx\n",mode,op,(unsigned long)r.cause,(unsigned long)r.tval,(unsigned long)r.epc);return 1;}
        if(!verify(&r,a,b)){ee_printf("MMU DATA FAIL mode=%u case=%u op=%u\n",mode,test,op);return 1;}
        uint64_t bytes=r.count*r.passes*8;
        ee_printf("MMU_BW mode=%s kind=%s op=%s pages_per_stream=%lu passes=%lu payload_bytes=%lu ticks=%lu flush_tail=%lu milli_MiB_s=%lu verified=1\n",
            mode==0?"S-Bare":mode==1?"Sv39-4K":"Sv39-2M",pages?"page_sweep":test?"128K_stream":"8K_warmed",
            op==0?"READ":op==1?"WRITE":"COPY",(unsigned long)(pages?pages:test?32:2),(unsigned long)r.passes,(unsigned long)bytes,
            (unsigned long)r.ticks,(unsigned long)r.tail,(unsigned long)(r.ticks?bytes*CPU_HZ*1000ULL/r.ticks/1048576ULL:0));
    }
    ee_printf("MMU_BANDWIDTH_PASS cases=54 data_verified=1 context_restored=1 copy_payload_not_double_bus=1\n");return 0;
}
#endif
