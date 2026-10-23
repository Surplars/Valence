#ifndef VALENCE_DVFS_ROUNDTRIP_H
#define VALENCE_DVFS_ROUNDTRIP_H
#include "valence_clock.h"
#ifndef DVFS_CPU_HZ
#define DVFS_CPU_HZ 50000000U
#endif
#ifndef DVFS_FABRIC_HZ
#define DVFS_FABRIC_HZ 50000000U
#endif
#ifndef DVFS_CPU_PARAMETERS
#define DVFS_CPU_PARAMETERS 0U
#endif
#ifndef DVFS_FABRIC_PARAMETERS
#define DVFS_FABRIC_PARAMETERS 0U
#endif
/* Diagnostic-only explicit tuple; never changes the shared canonical solver.
 * Fifty MHz always retains the canonical cold/fallback profile. */
static inline uint32_t dvfs_parameters(unsigned domain,uint32_t hz) {
    uint32_t packed=domain?DVFS_FABRIC_PARAMETERS:DVFS_CPU_PARAMETERS;
    uint32_t target=domain?DVFS_FABRIC_HZ:DVFS_CPU_HZ;
    if(!packed || hz!=target)return valence_clock_parameters(hz);
    unsigned d=packed&255,m=(packed>>8)&255,o=(packed>>16)&255;
    if(packed>>24 || d!=10 || m<32 || m>62 || o<3 || o>128 ||
       hz<10000000U || hz>(domain?250000000U:300000000U) ||
       UINT64_C(250000000)*m!=(uint64_t)hz*d*o ||
       (hz==50000000U && packed!=0x14280a))return 0;
    return packed;
}
/* Host-testable ordered test plan. Each step's observer verifies configured and
 * measured clocks, traffic, and scratch data before allowing the next step. */
struct dvfs_roundtrip_ops {
    void *context;
    int (*set)(void *, unsigned domain, uint32_t hz);
    int (*observe)(void *, uint32_t cpu_hz, uint32_t fabric_hz);
};
static inline int dvfs_roundtrip(const struct dvfs_roundtrip_ops *o) {
    static const uint32_t rates[4][3]={{0,DVFS_CPU_HZ,50000000},
        {1,DVFS_CPU_HZ,DVFS_FABRIC_HZ},{1,DVFS_CPU_HZ,50000000},{0,50000000,50000000}};
    if(o->observe(o->context,50000000,50000000))return -1;
    for(unsigned i=0;i<4;++i) {
        unsigned d=rates[i][0];
        if(o->set(o->context,d,rates[i][d+1]))return -(int)(2+i*2);
        if(o->observe(o->context,rates[i][1],rates[i][2]))return -(int)(3+i*2);
    }
    return 0;
}
static inline int dvfs_measured_matches(uint64_t measured,uint32_t expected) {
    uint64_t difference=measured>expected?measured-expected:expected-measured;
    /* Frequency-meter boundary uncertainty allowance, not timing margin. */
    return difference<=expected/100U;
}
#endif
