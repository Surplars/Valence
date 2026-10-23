#include <assert.h>
#include <stdio.h>
#include "dvfs_roundtrip.h"
static unsigned count,observed,fail_set,fail_observe;
static uint32_t rates[2]={50000000,50000000};
static const unsigned domains[4]={0,1,1,0};
static const uint32_t targets[4]={DVFS_CPU_HZ,DVFS_FABRIC_HZ,50000000,50000000};
static int set(void *p,unsigned d,uint32_t hz){(void)p;assert(count<4&&d==domains[count]&&hz==targets[count]);
    ++count;if(count==fail_set)return -1;rates[d]=hz;return 0;}
static int observe(void *p,uint32_t cpu,uint32_t fab){(void)p;++observed;assert(cpu==rates[0]&&fab==rates[1]);return observed==fail_observe?-1:0;}
static void reset(void){count=observed=fail_set=fail_observe=0;rates[0]=rates[1]=50000000;}
int main(void){struct dvfs_roundtrip_ops o={0,set,observe};
 assert(valence_clock_parameters(195000000)==0x05270a);assert(valence_clock_parameters(155000000)==0x0a3e0a);
 assert(valence_clock_parameters(50000000)==0x14280a);
#if DVFS_CPU_PARAMETERS
 assert(dvfs_parameters(0,DVFS_CPU_HZ)==DVFS_CPU_PARAMETERS);
#endif
#if DVFS_FABRIC_PARAMETERS
 assert(dvfs_parameters(1,DVFS_FABRIC_HZ)==DVFS_FABRIC_PARAMETERS);
#endif
 assert(!dvfs_roundtrip(&o)&&count==4&&observed==5);
 for(unsigned i=1;i<=4;++i){reset();fail_set=i;assert(dvfs_roundtrip(&o)<0&&count==i&&observed==i);}
 for(unsigned i=1;i<=5;++i){reset();fail_observe=i;assert(dvfs_roundtrip(&o)<0&&count==i-1&&observed==i);}
 assert(dvfs_measured_matches(195000000,195000000));assert(dvfs_measured_matches(193050000,195000000));
 assert(!dvfs_measured_matches(193049999,195000000));assert(!dvfs_measured_matches(50000000,195000000));
 puts("DVFS_ROUNDTRIP_HOST_PASS exact_tuples ordered_roundtrip stop_on_failure measurement_tolerance");}
