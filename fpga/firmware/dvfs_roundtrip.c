/* Dedicated RAM application, launched by BootROM download. No ROM changes.
 * It waits for a literal 'r' before requesting any frequency change. */
#include <stdint.h>
#include "dvfs_roundtrip.h"
#ifndef DVFS_SCRATCH_BYTES
#define DVFS_SCRATCH_BYTES 65536U
#endif
#define TIME_HZ UINT64_C(250000000)
#define POLLS 1000000U
_Static_assert(DVFS_SCRATCH_BYTES>=65536 && DVFS_SCRATCH_BYTES<=262144 &&
               DVFS_SCRATCH_BYTES%64==0,"scratch must be 64..256 KiB, 64B aligned");
static volatile uint64_t scratch[DVFS_SCRATCH_BYTES/8] __attribute__((aligned(64),section(".scratch")));
static uint64_t backup[DVFS_SCRATCH_BYTES/8] __attribute__((aligned(64)));
static volatile uint64_t sweep[65536/8] __attribute__((aligned(64),section(".scratch")));
static uint64_t last_seq[2],last_edges[2];
static unsigned have_sample[2],saved;
static uint64_t now(void){uint64_t n;__asm__ volatile("rdtime %0":"=r"(n)::"memory");return n;}
static void fence(void){__asm__ volatile("fence iorw,iorw":::"memory");}
static uint64_t mmread(void *c,uint64_t a){(void)c;fence();uint64_t v=*(volatile uint64_t *)(uintptr_t)a;fence();return v;}
static void mmwrite(void *c,uint64_t a,uint64_t v){(void)c;fence();*(volatile uint64_t *)(uintptr_t)a=v;fence();}
static const struct valence_clock_io io={0,mmread,mmwrite};
static void out(char c){volatile uint8_t *u=(volatile uint8_t *)0x10000000UL;for(unsigned i=0;i<POLLS;++i)if(u[5]&0x20){u[0]=(uint8_t)c;return;}}
static void text(const char *s){while(*s)out(*s++);}
static void hex(uint64_t n){for(int i=60;i>=0;i-=4){unsigned x=(unsigned)(n>>i)&15;out((char)(x<10?'0'+x:'a'+x-10));}}
static void field(const char *s,uint64_t v){text(s);hex(v);}
static void status(unsigned d){uint64_t b=d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU;
    text(d?"FABRIC":"CPU");field(" requested=0x",mmread(0,b+RATE_REQUEST));field(" configured=0x",mmread(0,b+RATE_CONFIGURED));
    field(" status=0x",mmread(0,b+RATE_STATUS));field(" errors=0x",mmread(0,b+RATE_ERRORS));field(" completed=0x",mmread(0,b+RATE_COMPLETED));text("\r\n");}
/* Platform-specific documented cache maintenance: fence.i writes dirty lines
 * back; a disjoint64KiB read-only sweep evicts clean lines on current <=32KiB
 * one/two-way caches. This is not a portable RISC-V fence.i guarantee. */
static void cold(void){uint64_t consume=0;__asm__ volatile("fence rw,rw\nfence.i\nfence rw,rw":::"memory");
    for(unsigned p=0;p<2;++p)for(unsigned i=0;i<sizeof(sweep)/8;i+=8)consume^=sweep[i];
    __asm__ volatile(""::"r"(consume):"memory");fence();}
static uint64_t pattern(unsigned i){return UINT64_C(0x9e3779b97f4a7c15)*(i+1)^UINT64_C(0xa55a1234deadbeef);}
static int memory_check(void){cold();uint64_t checksum=0;for(unsigned i=0;i<DVFS_SCRATCH_BYTES/8;++i){uint64_t v=scratch[i];
    if(v!=pattern(i)){field("DDR_MISMATCH address=0x",(uintptr_t)&scratch[i]);field(" value=0x",v);text("\r\n");return -1;}checksum^=v;}
    field("DDR_PATTERN_OK checksum=0x",checksum);text("\r\n");return 0;}
static int sample(unsigned d,uint32_t expected){struct valence_perf_snapshot s;uint64_t base=d?VALENCE_PERF_FABRIC:VALENCE_PERF_CPU;
    uint64_t deadline=now();unsigned fresh=0;
    /* Require TWO new valid windows after each transition; never reuse the
     * previous rate's sample. Always bounded in reference-time and iterations. */
    for(unsigned attempt=0;attempt<20000 && now()-deadline<TIME_HZ;++attempt){
        if(valence_perf_read(&io,base,&s,2))continue;
        if(have_sample[d]&&s.sequence==last_seq[d])continue;
        if(have_sample[d] && (uint32_t)(s.total[0]-last_edges[d])==0)continue;
        have_sample[d]=1;last_seq[d]=s.sequence;last_edges[d]=s.total[0];
        if(++fresh<2)continue;
        uint64_t hz=valence_perf_measured_hz(&s);text(d?"FABRIC_METER":"CPU_METER");field(" Hz=0x",hz);field(" sequence=0x",s.sequence);
        field(" window_edges=0x",s.delta[0]);field(d?" AXI_R_beats=0x":" retire0=0x",s.delta[d?5:1]);text("\r\n");
        if(!s.delta[0] || (!d&&!s.delta[1]) || !dvfs_measured_matches(hz,expected))return -1;
        return 0;
    }
    text("METER_TIMEOUT_STALE_OR_INVALID\r\n");return -1;
}
static int observe(void *ctx,uint32_t cpu,uint32_t fabric){(void)ctx;
    status(0);status(1);
    if(mmread(0,VALENCE_RATE_CPU+RATE_CONFIGURED)!=cpu || mmread(0,VALENCE_RATE_FABRIC+RATE_CONFIGURED)!=fabric)return -1;
    if(sample(0,cpu) || sample(1,fabric))return -1;
    struct valence_perf_snapshot before,after;
    if(valence_perf_read(&io,VALENCE_PERF_FABRIC,&before,8))return -1;
    if(memory_check() || sample(0,cpu) || sample(1,fabric))return -1;
    if(valence_perf_read(&io,VALENCE_PERF_FABRIC,&after,8))return -1;
    uint32_t read_beats=after.total[5]-before.total[5];
    field("DDR_OBSERVED_AXI_R_BEATS=0x",read_beats);text("\r\n");
    if(!read_beats){text("NO_DDR_READ_TRAFFIC_OBSERVED\r\n");return -1;}
    return 0;
}
static int set_rate(void *ctx,unsigned d,uint32_t hz){(void)ctx;uint64_t b=d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU;
    text(d?"SET_FABRIC":"SET_CPU");field(" Hz=0x",hz);field(" MDO=0x",valence_clock_parameters(hz));text("\r\n");
    int rc=valence_rate_set(&io,b,hz,POLLS);field("SET_RESULT signed=0x",(uint64_t)(int64_t)rc);text("\r\n");status(d);return rc;
}
static int preflight(void){
    if(valence_clock_parameters(195000000)!=0x05270a || valence_clock_parameters(155000000)!=0x0a3e0a ||
       valence_clock_parameters(50000000)!=0x14280a)return -1;
    for(unsigned d=0;d<2;++d){uint64_t b=d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU;
        if(!valence_rate_v2(&io,b))return -1;
        status(d);uint64_t s=mmread(0,b+RATE_STATUS);
        if((s&(RATE_BUSY|RATE_FATAL)) || (s&(RATE_PRESENT|RATE_VALID))!=(RATE_PRESENT|RATE_VALID) ||
           mmread(0,b+RATE_CONFIGURED)!=50000000 || mmread(0,b+RATE_ERRORS) ||
           mmread(0,b+RATE_CAPS)!=UINT64_C(0x000080033e200a0a) ||
           mmread(0,b+RATE_REFERENCE)!=250000000 || !(mmread(0,b+RATE_ADMISSION)&32) ||
           mmread(0,b+RATE_MIN)>50000000 || mmread(0,b+RATE_MAX)<(d?155000000:195000000))return -1;
    }
    return 0;
}
static void restore_low(void){/* Best effort only, never issue into busy/fatal state. */
    for(int d=1;d>=0;--d){uint64_t b=d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU,s=mmread(0,b+RATE_STATUS);
        uint64_t start=now();
        for(unsigned poll=0;poll<100000 && (s&RATE_BUSY) && !(s&RATE_FATAL) && now()-start<TIME_HZ;++poll)
            s=mmread(0,b+RATE_STATUS);
        if((s&(RATE_BUSY|RATE_FATAL)) || !(s&RATE_PRESENT)){text("RECOVERY_BLOCKED_BUSY_FATAL_RESET_REQUIRED\r\n");continue;}
        if(mmread(0,b+RATE_CONFIGURED)!=50000000)set_rate(0,(unsigned)d,50000000);
    }
}
int main(void){text("RAM DVFS diagnostic; no automatic overclock. Reset after completion.\r\n");
    field("scratch_begin=0x",(uintptr_t)scratch);field(" scratch_bytes=0x",sizeof(scratch));field(" sweep_begin=0x",(uintptr_t)sweep);text("\r\n");
    text("Dedicated boot only; no Linux/kernel/other live payload may own this linked RAM allocation.\r\n");
    text("Type r within60s: 50/50 ->195/50 ->195/155 ->195/50 ->50/50; q exits.\r\n");
    volatile uint8_t *u=(volatile uint8_t *)0x10000000UL;uint64_t start=now();int run=0;
    while(now()-start<60*TIME_HZ){if(u[5]&1){int c=u[0];if(c=='r'){run=1;break;}if(c=='q')break;}}
    if(!run){text("CANCELLED_NO_CLOCK_CHANGE\r\n");return 0;}
    if(preflight()){text("PREFLIGHT_FAIL_REQUIRE_IDLE_ERRORFREE_50_50_AND_COMPATIBLE_PROFILES_NO_CHANGE\r\n");return 1;}
    if(mmread(0,0x10001020)&1){text("DMA_BUSY_NO_CHANGE\r\n");return 1;}
    cold();for(unsigned i=0;i<DVFS_SCRATCH_BYTES/8;++i)backup[i]=scratch[i];saved=1;
    for(unsigned i=0;i<DVFS_SCRATCH_BYTES/8;++i)scratch[i]=pattern(i);
    const struct dvfs_roundtrip_ops ops={0,set_rate,observe};int rc=dvfs_roundtrip(&ops);
    if(rc){field("ROUNDTRIP_FAILED_STAGE signed=0x",(uint64_t)(int64_t)rc);text("\r\n");restore_low();}
    if(saved){for(unsigned i=0;i<DVFS_SCRATCH_BYTES/8;++i)scratch[i]=backup[i];cold();
        for(unsigned i=0;i<DVFS_SCRATCH_BYTES/8;++i)if(scratch[i]!=backup[i]){text("SCRATCH_RESTORE_FAILED\r\n");rc=-99;break;}}
    status(0);status(1);text(rc?"DVFS_ROUNDTRIP_FAIL_RESET_REQUIRED\r\n":"DVFS_ROUNDTRIP_PASS_DIAGNOSTIC_ONLY\r\n");return rc?1:0;
}
