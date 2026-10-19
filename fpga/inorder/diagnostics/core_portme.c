#include "coremark.h"
#include "platform.h"
volatile ee_s32 seed1_volatile=0, seed2_volatile=0, seed3_volatile=0x66;
volatile ee_s32 seed4_volatile=0, seed5_volatile=0;
ee_u32 default_num_contexts=1;
uint64_t cm_cycles, cm_instructions, cm_ticks, cm_iterations;
unsigned cm_crcs[5], cm_validated, cm_errors;
static uint64_t begin_time, begin_cycles, begin_instructions;
void start_time(void) { begin_time=ticks(); begin_cycles=cycles(); begin_instructions=retired(); }
void stop_time(void) { cm_instructions=retired()-begin_instructions; cm_cycles=cycles()-begin_cycles; cm_ticks=ticks()-begin_time; }
CORE_TICKS get_time(void) { return cm_ticks; }
secs_ret time_in_secs(CORE_TICKS value) { return (double)value/(double)CPU_HZ; }
void portable_init(core_portable *p, int *argc, char *argv[]) { (void)argc; (void)argv; p->portable_id=1; }
void portable_fini(core_portable *p) { p->portable_id=0; }
static int starts(const char *a,const char *b) { while(*b && *a==*b) { ++a; ++b; } return !*b; }
int ee_printf(const char *fmt,...) {
    va_list ap, copy; va_start(ap,fmt); va_copy(copy,ap);
    if(starts(fmt,"seedcrc")) cm_crcs[0]=va_arg(copy,int);
    else if(starts(fmt,"[%d]crc")) {
        (void)va_arg(copy,int);
        unsigned i=starts(fmt,"[%d]crclist")?1:starts(fmt,"[%d]crcmatrix")?2:starts(fmt,"[%d]crcstate")?3:4;
        cm_crcs[i]=va_arg(copy,int);
    } else if(starts(fmt,"Iterations       :")) cm_iterations=va_arg(copy,unsigned long);
    else if(starts(fmt,"Correct operation validated")) cm_validated=1;
    else if(starts(fmt,"Errors detected") || starts(fmt,"Cannot validate")) cm_errors=1;
    va_end(copy); int result=diag_vprintf(fmt,ap); va_end(ap); return result;
}
int coremark_main(void);
void run_coremark(int short_run) {
    cm_validated=cm_errors=0;
    for(unsigned i=0;i<5;++i) cm_crcs[i]=0;
    seed4_volatile=short_run?1:0;
    diag_printf("\nCoreMark O3 %s, integer RV64IM workload; software-float reporting only.\n",
        short_run?"SMOKE (NOT A SCORE)":"FORMAL automatic >=10s");
    coremark_main();
    diag_printf("COUNTERS cycles=%lu instructions=%lu IPC=",cm_cycles,cm_instructions);
    print_ratio(cm_instructions,cm_cycles,6);
    diag_printf(" time_ticks=%lu clock_hz=%lu\n",cm_ticks,(unsigned long)CPU_HZ);
    if(!short_run && cm_validated && !cm_errors && cm_ticks>=10UL*CPU_HZ) {
        diag_printf("CoreMark/MHz: ");
        print_ratio(cm_iterations*1000000UL,cm_ticks,6);
        diag_printf("\nFORMAL_RESULT_VALID (not an EEMBC certification/submission)\n");
    } else diag_printf(short_run?"SMOKE_ONLY; duration warning expected, do not report as a score.\n":"FORMAL_RESULT_INVALID\n");
}
