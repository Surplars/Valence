#include "platform.h"
#ifndef DIAG_AUTOTEST
#define DIAG_AUTOTEST 0
#endif
static uint64_t root[512] __attribute__((aligned(4096)));
static uint64_t alias_l1[512] __attribute__((aligned(4096)));
static uint64_t alias_l0[9][512] __attribute__((aligned(4096)));
static uint64_t test_bytes, test_repetitions, test_source, test_destination;
struct sample { uint64_t time, cycle, instructions, sum, errors; };
static struct sample results[4];
/* Host checks this via a real coherent probe, not direct access to dirty RAM. */
volatile uint64_t diag_receipt[32];
static uint64_t pte(uint64_t address, uint64_t flags) { return (address>>2)|flags; }
static void initialize_paging(void) {
    /* Executable/stack identity mapping; data aliases use actual three-level
       4KiB walks. No SUM/MPRV emulation masquerading as a complete S-mode run. */
    root[0]=pte(0,0xcf);
    root[2]=pte(0x80000000UL,0xcf);
    root[3]=pte(0xc0000000UL,0xcf);
    root[4]=pte(0x100000000UL,0xcf);
    root[1]=pte((uint64_t)alias_l1,1);
    unsigned table=0;
    for(unsigned kind=0;kind<2;++kind) {
        uint64_t va=kind?0x43000000UL:SOURCE_VA;
        uint64_t pa=kind?0x83000000UL:SOURCE_PA;
        unsigned count=kind?5:4;
        for(unsigned i=0;i<count;++i,++table) {
            alias_l1[((va>>21)+i)&511]=pte((uint64_t)alias_l0[table],1);
            for(unsigned j=0;j<512;++j)
                alias_l0[table][j]=pte(pa+((uint64_t)i<<21)+((uint64_t)j<<12),0xc7);
        }
    }
    fence_memory();
}
static void set_translation(int sv39) {
    uint64_t value=sv39?((8UL<<60)|((uint64_t)root>>12)):0;
    __asm__ volatile("csrw satp,%0; sfence.vma" :: "r"(value) : "memory");
}
static uint64_t verify(const uint64_t *p, size_t bytes, uint64_t seed) {
    const volatile uint64_t *data=p;
    uint64_t errors=0;
    for(size_t i=0;i<bytes/8;++i) if(data[i]!=seed+i) ++errors;
    return errors;
}
static void sample_begin(struct sample *s) {
    fence_memory();
    s->time=ticks(); s->cycle=cycles(); s->instructions=retired();
}
static void sample_end(struct sample *s) {
    fence_memory();
    s->instructions=retired()-s->instructions; s->cycle=cycles()-s->cycle; s->time=ticks()-s->time;
}
static void bandwidth_job(void) {
    uint64_t *src=(uint64_t *)test_source, *dst=(uint64_t *)test_destination;
    size_t bytes=test_bytes;
    stream_write(src,bytes,PATTERN);
    stream_write(dst,bytes,0);
    uint64_t words=bytes/8, expected=words*PATTERN+words*(words-1)/2;
    for(unsigned i=0;i<4;++i) results[i].errors=results[i].sum=0;
    sample_begin(&results[0]);
    for(unsigned i=0;i<test_repetitions;++i) results[0].sum+=stream_read(src,bytes);
    sample_end(&results[0]);
    if(results[0].sum!=expected*test_repetitions) ++results[0].errors;
    sample_begin(&results[1]);
    for(unsigned i=0;i<test_repetitions;++i) stream_write(dst,bytes,0xabc00000UL);
    sample_end(&results[1]);
    results[1].errors=verify(dst,bytes,0xabc00000UL);
    sample_begin(&results[2]);
    for(unsigned i=0;i<test_repetitions;++i) scalar_copy(dst,src,bytes);
    sample_end(&results[2]);
    results[2].errors=verify(dst,bytes,PATTERN);
    sample_begin(&results[3]);
    for(unsigned i=0;i<test_repetitions;++i) stream_copy(dst,src,bytes);
    sample_end(&results[3]);
    results[3].errors=verify(dst,bytes,PATTERN)+verify(src,bytes,PATTERN);
}
static void guard_job(void) {
    /* Intentionally absent PTE: proof that Sv39 was not silently bypassed. */
    diag_receipt[30]=*(volatile uint64_t *)0x45000000UL;
}
static unsigned bandwidth(int sv39, size_t bytes, unsigned repetitions) {
    if(bytes<64 || bytes>8UL*1024*1024 || bytes%64 || !repetitions) return 1;
    test_bytes=bytes; test_repetitions=repetitions;
    test_source=sv39?SOURCE_VA:SOURCE_PA;
    test_destination=sv39?DEST_VA:DEST_PA;
    diag_printf("\nS-mode %s bytes=%lu repetitions=%u; same loops, 64B unroll\n",
        sv39?"Sv39/4KiB nonidentity data":"Bare",(unsigned long)bytes,repetitions);
    set_translation(sv39);
    int failed=run_supervisor(bandwidth_job);
    set_translation(0);
    if(failed) {
        diag_printf("BANDWIDTH_TRAP cause=%lu pc=0x%lx tval=0x%lx\n",trap_cause,trap_pc,trap_value);
        return 1;
    }
    const char *names[]={"READ64_U8","WRITE64_U8","COPY_SCALAR","COPY_U8"};
    unsigned errors=0;
    for(unsigned i=0;i<4;++i) {
        struct sample *s=&results[i];
        errors+=(unsigned)s->errors;
        diag_printf("%s bytes=%lu ticks=%lu cycles=%lu instructions=%lu IPC=",names[i],bytes*repetitions,s->time,s->cycle,s->instructions);
        print_ratio(s->instructions,s->cycle,4);
        diag_printf(" payload_MiB/s=");
        print_ratio(bytes*repetitions*CPU_HZ,s->time*1048576UL,3);
        if(i>=2) {
            diag_printf(" logical_R+W_MiB/s=");
            print_ratio(bytes*repetitions*CPU_HZ*2,s->time*1048576UL,3);
        }
        diag_printf(" %s\n",s->errors?"FAIL":"PASS");
    }
    diag_printf("BANDWIDTH_%s errors=%u; cache enabled, dirty tail NOT explicitly drained.\n",errors?"FAIL":"PASS",errors);
    return errors;
}
static void info(void) {
    uint64_t misa;
    __asm__ volatile("csrr %0,misa" : "=r"(misa));
    diag_printf("OpenIon Orbital-I1 / batch44 CPU300 / I32KiB D32KiB / TL-C / USER2 / no MAC\n");
    diag_printf("clock_hz=%lu UART460800 8N1; misa=0x%lx; real cycle/time/instret counters\n",(unsigned long)CPU_HZ,misa);
    diag_printf("64-bit AXI @CPU300 ideal one-direction ceiling: 2400 MB/s (2288.818 MiB/s).\n");
    diag_printf("This is NOT measured MIG bandwidth. No AXI utilization counters in this bit.\n");
    diag_printf("Tests measure CPU->L1->TL-C/Home->AXI->CDC->MIG path, not raw bus utilization.\n");
    diag_printf("Destructive scratch: 0x81000000..0x81800000, 0x83000040..0x83800040.\n");
    diag_printf("No UART/validation in timed loops; full data verification after timing.\n");
    diag_printf("Plain fence orders memory; it does NOT flush this bit's write-back D-cache.\n");
}
static void menu(void) {
    diag_printf("\n[c] O3 CoreMark >=10s  [k] CoreMark 1 iteration (NOT score)\n");
    diag_printf("[b] Bare 1MiB [m] Sv39/4K 1MiB [p] both [l] both 8MiB\n");
    diag_printf("[h] cache 16KiB x256 [t] CPU/bus-path test (both 1MiB)\n");
    diag_printf("[s] short checks [d] DMA status [i] info [?] menu\nI1> ");
}
static unsigned short_checks(void) {
    unsigned failures=bandwidth(0,256,1);
    uint64_t bare_sum=results[0].sum;
    diag_receipt[3]=bare_sum;
    for(unsigned i=0;i<4;++i) diag_receipt[8+i]=results[i].time;
    failures+=bandwidth(1,256,1);
    diag_receipt[4]=results[0].sum;
    for(unsigned i=0;i<4;++i) diag_receipt[12+i]=results[i].time;
    if(results[0].sum!=bare_sum) ++failures;
    set_translation(1);
    int faulted=run_supervisor(guard_job);
    set_translation(0);
    diag_receipt[5]=trap_cause; diag_receipt[6]=trap_value;
    if(!faulted || trap_cause!=13 || trap_value!=0x45000000UL) ++failures;
    run_coremark(1);
    for(unsigned i=0;i<5;++i) diag_receipt[16+i]=cm_crcs[i];
    if(cm_crcs[0]!=0xe9f5 || cm_crcs[1]!=0xe714 || cm_crcs[2]!=0x1fd7 || cm_crcs[3]!=0x8e3a) ++failures;
    diag_receipt[21]=cm_cycles; diag_receipt[22]=cm_instructions; diag_receipt[23]=cm_ticks;
    diag_receipt[24]=cm_iterations;
    diag_printf("SHORT_CHECKS_%s errors=%u (NOT a performance score)\n",failures?"FAIL":"PASS",failures);
    diag_receipt[2]=failures;
    return failures;
}
int main(void) {
    quiet_output=DIAG_AUTOTEST;
    initialize_paging();
    diag_receipt[0]=0x4931444941473031UL;
    if(DIAG_AUTOTEST) {
        int failures=short_checks();
        diag_receipt[1]=1;
        fence_memory();
        return failures;
    }
    diag_printf("\nValence I1 Diagnostics V0.1 / CPU300 / UART460800\n");
    info(); menu();
    for(;;) {
        int c=getchar_uart();
        if(c=='\r' || c=='\n' || c==0x11 || c==0x13) continue;
        putchar_uart(c); putchar_uart('\n');
        switch(c) {
        case 'c': run_coremark(0); break;
        case 'k': run_coremark(1); break;
        case 'b': bandwidth(0,1048576,1); break;
        case 'm': bandwidth(1,1048576,1); break;
        case 'p': case 't': bandwidth(0,1048576,1); bandwidth(1,1048576,1); break;
        case 'l': bandwidth(0,8388608,1); bandwidth(1,8388608,1); break;
        case 'h': bandwidth(0,16384,256); break;
        case 's': short_checks(); break;
        case 'd': diag_printf("DMA_UNAVAILABLE: no general memcpy DMA in this I1 no-MAC bit; no MMIO probed.\n"); break;
        case 'i': info(); break;
        case '?': break;
        default: diag_printf("Unknown selection.\n"); break;
        }
        menu();
    }
}
