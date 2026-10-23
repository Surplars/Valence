/* Execute the real main/observer/scratch restoration against deterministic
 * MMIO/time/UART/cache hooks; no claim of hardware timing or physical DDR. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define DVFS_PAYLOAD_TEST 1
#define main payload_main
#include "dvfs_roundtrip.c"
#undef main
static uint64_t regs[2][16],seq_reads[2],current_seq[2],ticks;
static unsigned requests,input_mode,error_stage,stale,bad_meter,no_traffic,corrupt,restoration_corrupt,cold_count;
static uint32_t seen_hz[8];static unsigned seen_domain[8];
static char logbuf[32768];static unsigned logused;
uint64_t dvfs_test_now(void){return ticks+=1000000;}
void dvfs_test_out(char c){assert(logused+1<sizeof logbuf);logbuf[logused++]=c;logbuf[logused]=0;}
int dvfs_test_input(void){return input_mode==2?-1:input_mode?'r':'q';}
void dvfs_test_cold(void){++cold_count;
    if(corrupt&&requests==1){scratch[0]^=1;corrupt=0;}
    if(restoration_corrupt&&requests==4&&cold_count>=7)scratch[0]^=1;
}
uint64_t dvfs_test_read(void *ctx,uint64_t a){(void)ctx;
    if(a==0x10001020)return 0;
    if(a>=VALENCE_PERF_CPU){unsigned d=a>=VALENCE_PERF_FABRIC;unsigned off=(unsigned)(a-(d?VALENCE_PERF_FABRIC:VALENCE_PERF_CPU));
        if(off==0){uint64_t seq=stale?1:seq_reads[d]/2+1;current_seq[d]=seq;++seq_reads[d];return seq;}
        if(off==8)return 1;
        if(off==0x10)return 50000000;
        if(off==0x18)return 50000;
        if(off==0x28)return UINT64_C(0x544d002000000001);
        if(off==0x40)return bad_meter?50000:regs[d][RATE_CONFIGURED/8]/1000;
        if(off>=0x40&&off<0x80)return 100;
        if(off==0xa8&&no_traffic)return 0;
        if(off>=0x80&&off<0xc0)return current_seq[d]*1000;
        return 0;
    }
    unsigned d=a>=VALENCE_RATE_FABRIC,off=(unsigned)(a-(d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU))/8;
    assert(off<16);return regs[d][off];
}
void dvfs_test_write(void *ctx,uint64_t a,uint64_t value){(void)ctx;
    unsigned d=a>=VALENCE_RATE_FABRIC,off=(unsigned)(a-(d?VALENCE_RATE_FABRIC:VALENCE_RATE_CPU))/8;
    if(off==RATE_ERRORS/8){regs[d][off]&=~value;return;}
    regs[d][off]=value;
    if(off==RATE_REQUEST/8){assert(regs[d][RATE_PARAMETERS/8]==dvfs_parameters(d,(uint32_t)value));assert(requests<8);seen_domain[requests]=d;seen_hz[requests]=value;++requests;
        if(requests==error_stage){regs[d][RATE_ERRORS/8]=1U<<7;return;}
        regs[d][RATE_CONFIGURED/8]=value;regs[d][RATE_COMPLETED/8]++;
        regs[d][RATE_STATUS/8]=RATE_PRESENT|RATE_VALID|RATE_SUCCESS;}
}
static void reset(void){memset(regs,0,sizeof regs);memset(seq_reads,0,sizeof seq_reads);memset(have_sample,0,sizeof have_sample);
    requests=ticks=logused=error_stage=stale=bad_meter=no_traffic=corrupt=restoration_corrupt=cold_count=saved=0;input_mode=1;logbuf[0]=0;
    for(unsigned d=0;d<2;++d){regs[d][RATE_ID/8]=UINT64_C(0x4352000300000002);regs[d][RATE_CAPS/8]=UINT64_C(0x000080033e200a0a);
        regs[d][RATE_REFERENCE/8]=250000000;regs[d][RATE_ADMISSION/8]=0x30;regs[d][RATE_MIN/8]=10000000;regs[d][RATE_MAX/8]=d?250000000:300000000;
        regs[d][RATE_STATUS/8]=RATE_PRESENT|RATE_VALID;regs[d][RATE_CONFIGURED/8]=50000000;}
    for(unsigned i=0;i<DVFS_SCRATCH_BYTES/8;++i)scratch[i]=i^0xabc;
}
static void restored(void){for(unsigned i=0;i<DVFS_SCRATCH_BYTES/8;++i)assert(scratch[i]==(i^0xabc));}
int main(void){reset();input_mode=0;assert(!payload_main()&&!requests);restored();
    reset();input_mode=2;assert(!payload_main()&&!requests);restored();
    reset();assert(!payload_main()&&requests==4);restored();
    assert(seen_domain[0]==0&&seen_hz[0]==DVFS_CPU_HZ&&seen_domain[1]==1&&seen_hz[1]==DVFS_FABRIC_HZ);
    assert(seen_domain[2]==1&&seen_hz[2]==50000000&&seen_domain[3]==0&&seen_hz[3]==50000000);
    reset();regs[1][RATE_CONFIGURED/8]=100000000;assert(payload_main()&&!requests);restored();
    reset();regs[0][RATE_STATUS/8]|=RATE_BUSY;assert(payload_main()&&!requests);restored();
    reset();regs[1][RATE_CAPS/8]=0;assert(payload_main()&&!requests);restored();
    reset();stale=1;assert(payload_main()&&!requests);restored();
    reset();no_traffic=1;assert(payload_main()&&!requests);restored();
    reset();error_stage=2;assert(payload_main());assert(regs[0][RATE_CONFIGURED/8]==50000000);restored();
#if DVFS_CPU_HZ != 50000000U
    reset();bad_meter=1;assert(payload_main()&&requests==2);restored();
#endif
    reset();corrupt=1;assert(payload_main());assert(strstr(logbuf,"DDR_MISMATCH"));restored();
    reset();restoration_corrupt=1;assert(payload_main());assert(strstr(logbuf,"SCRATCH_RESTORE_FAILED"));
    puts("DVFS_PAYLOAD_MAIN_HOST_PASS manual ordered fresh_meter traffic errors recovery scratch_restore");
}
