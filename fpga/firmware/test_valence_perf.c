#include <assert.h>
#include <stdio.h>
#include "valence_clock.h"
static unsigned mode,seq_reads,flag_reads;
static uint64_t read_perf(void *context,uint64_t address) {
    (void)context;unsigned o=(unsigned)(address-VALENCE_PERF_CPU);
    if(o==0){++seq_reads;return mode==1?seq_reads:7;}
    if(o==8){++flag_reads;return mode==2&&flag_reads%2==0?5:mode==3?5:1;}
    if(o==0x10)return 50000000;
    if(o==0x18)return mode==4?0:50000;
    if(o==0x20)return 350000;
    if(o==0x28)return mode==5?0:UINT64_C(0x544d002000000001);
    if(o==0x40)return mode==6?0:75000;
    return 123;
}
int main(void) {
    const struct valence_clock_io io={0,read_perf,0};struct valence_perf_snapshot s;
    assert(!valence_perf_read(&io,VALENCE_PERF_CPU,&s,3));
    assert(s.sequence==7 && s.delta[1]==123 && s.total[7]==123);
    assert(valence_perf_measured_hz(&s)==75000000);
    mode=1;seq_reads=0;assert(valence_perf_read(&io,VALENCE_PERF_CPU,&s,3)==-3 && seq_reads==6);
    mode=2;flag_reads=0;assert(valence_perf_read(&io,VALENCE_PERF_CPU,&s,3)==-3);
    mode=3;assert(valence_perf_read(&io,VALENCE_PERF_CPU,&s,3)==-2);
    mode=4;assert(valence_perf_read(&io,VALENCE_PERF_CPU,&s,3)==-2);
    mode=5;assert(valence_perf_read(&io,VALENCE_PERF_CPU,&s,3)==-1);
    mode=6;assert(!valence_perf_read(&io,VALENCE_PERF_CPU,&s,3) && !valence_perf_measured_hz(&s));
    puts("VALENCE_PERF_PASS coherent rollover live_invalidate stale zero_window wrong_abi zero_edges");
}
