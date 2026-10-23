#ifndef VALENCE_CLOCK_H
#define VALENCE_CLOCK_H
#include <stdint.h>
/* CMU rate ABI v2. The caller serializes the complete transaction (including
 * staging), and supplies ordered 64-bit MMIO operations. Linux callers must
 * use mapped device I/O, not physical-address pointer casts. No U-Boot needed.
 * This API does not qualify a rate or install a Linux cpufreq policy. */
#define VALENCE_RATE_CPU UINT64_C(0x10080800)
#define VALENCE_RATE_FABRIC UINT64_C(0x10080880)
enum { RATE_REQUEST=0, RATE_CONFIGURED=8, RATE_STATUS=0x10, RATE_ERRORS=0x18,
    RATE_TARGET=0x20, RATE_BOOT=0x28, RATE_PARAMETERS=0x30, RATE_CAPS=0x38,
    RATE_ADMISSION=0x40, RATE_TIMEOUT=0x48, RATE_COMPLETED=0x50,
    RATE_STATE=0x58, RATE_MAX=0x60, RATE_MIN=0x68, RATE_REFERENCE=0x70, RATE_ID=0x78 };
enum { RATE_BUSY=1, RATE_VALID=2, RATE_SUCCESS=256, RATE_FATAL=512, RATE_PRESENT=1024 };
struct valence_clock_io {
    void *context;
    uint64_t (*read)(void *, uint64_t);
    void (*write)(void *, uint64_t, uint64_t);
};
static inline uint64_t valence_rate_read(const struct valence_clock_io *io, uint64_t base, unsigned off) {
    return io->read(io->context, base+off);
}
static inline int valence_rate_v2(const struct valence_clock_io *io, uint64_t base) {
    uint64_t id=valence_rate_read(io,base,RATE_ID);
    return (id>>48)==0x4352 && (id&0xffff)==2 && (id & (UINT64_C(1)<<32));
}
/* Exact integer solution; cross-products avoid rounding a requested clock into
 * an unsupported rate. Limits describe this ZU15EG -2 native backend, not all
 * MMCMs. Search order is deterministic and uses the fixed 25 MHz PFD for UI250. */
static inline uint32_t valence_clock_parameters(uint32_t hz) {
    if(hz<10000000U || hz>300000000U) return 0;
    /* Match the native tested initial profiles, including boot/fallback50.
     * This is software policy, not a hardware frequency whitelist. */
    if(hz>=50000000U && hz<=150000000U && hz%5000000U==0) {
        unsigned o=hz<=75000000U?20:10;
        unsigned m=(unsigned)((uint64_t)hz*o/25000000U);
        return 10|(m<<8)|(o<<16);
    }
    for(unsigned d=10;d<=10;++d)
        for(unsigned o=3;o<=128;++o)
            for(unsigned m=32;m<=62;++m)
                if(UINT64_C(250000000)*m==(uint64_t)hz*d*o)
                    return d|(m<<8)|(o<<16);
    return 0;
}
enum valence_rate_result { RATE_OK=0, RATE_BAD_ABI=-1, RATE_BAD_FREQUENCY=-2,
    RATE_NOT_READY=-3, RATE_FAILED=-4, RATE_POLL_TIMEOUT=-5, RATE_NOT_ADMITTED=-6 };
/* Bounded by MMIO polls, independent of rdtime rate and clock stoppage. The
 * always-on controller owns all gate/DRP/lock/resume steps while CPU is stopped.
 * Timeout is not cancellation: inspect state before attempting another change. */
static inline int valence_rate_set(const struct valence_clock_io *io, uint64_t base,
                                   uint32_t hz, unsigned polls) {
    if(!valence_rate_v2(io,base) ||
       valence_rate_read(io,base,RATE_CAPS)!=UINT64_C(0x000080033e200a0a) ||
       valence_rate_read(io,base,RATE_REFERENCE)!=250000000U)return RATE_BAD_ABI;
    /* ABI v2 strict mode does not expose per-target qualification proof.
     * Do not issue a write that would bus-fault merely to discover admission. */
    if(!(valence_rate_read(io,base,RATE_ADMISSION)&32))return RATE_NOT_ADMITTED;
    uint32_t params=valence_clock_parameters(hz);
    if(!params || hz<valence_rate_read(io,base,RATE_MIN) || hz>valence_rate_read(io,base,RATE_MAX))
        return RATE_BAD_FREQUENCY;
    uint64_t status=valence_rate_read(io,base,RATE_STATUS);
    if(!(status&RATE_PRESENT) || (status&(RATE_BUSY|RATE_FATAL)))return RATE_NOT_READY;
    uint64_t before=valence_rate_read(io,base,RATE_COMPLETED);
    uint64_t errors=valence_rate_read(io,base,RATE_ERRORS);
    if(errors)io->write(io->context,base+RATE_ERRORS,errors); /* W1C observed bits only */
    io->write(io->context,base+RATE_PARAMETERS,params);
    io->write(io->context,base+RATE_REQUEST,hz); /* atomic staging snapshot */
    while(polls--) {
        status=valence_rate_read(io,base,RATE_STATUS);
        errors=valence_rate_read(io,base,RATE_ERRORS);
        if(errors || (status&RATE_FATAL))return RATE_FAILED;
        if(!(status&RATE_BUSY) && valence_rate_read(io,base,RATE_COMPLETED)!=before)
            return (status&(RATE_VALID|RATE_SUCCESS))==(RATE_VALID|RATE_SUCCESS) &&
                valence_rate_read(io,base,RATE_CONFIGURED)==hz ? RATE_OK : RATE_FAILED;
    }
    return RATE_POLL_TIMEOUT;
}
#define VALENCE_PERF_CPU UINT64_C(0x10080900)
#define VALENCE_PERF_FABRIC UINT64_C(0x10080a00)
struct valence_perf_snapshot {
    uint64_t sequence, flags, reference_hz, window, timestamp;
    uint32_t delta[8], total[8];
};
/* Read coherent published counters; live invalidate is checked on BOTH sides.
 * A zero-edge interval is meaningful, but is not evidence of a safe clock. */
static inline int valence_perf_read(const struct valence_clock_io *io, uint64_t base,
                                    struct valence_perf_snapshot *s, unsigned retries) {
    uint64_t id=io->read(io->context,base+0x28);
    if((id>>48)!=0x544d || (id&0xffff)!=1)return -1;
    while(retries--) {
        s->sequence=io->read(io->context,base);
        s->flags=io->read(io->context,base+8);
        s->reference_hz=io->read(io->context,base+0x10);
        s->window=io->read(io->context,base+0x18);
        s->timestamp=io->read(io->context,base+0x20);
        for(unsigned i=0;i<8;++i) {
            s->delta[i]=(uint32_t)io->read(io->context,base+0x40+8*i);
            s->total[i]=(uint32_t)io->read(io->context,base+0x80+8*i);
        }
        uint64_t flags=io->read(io->context,base+8);
        if(s->sequence==io->read(io->context,base) && s->flags==flags)
            return (flags&5)==1 && s->window ? 0 : -2;
    }
    return -3;
}
static inline uint64_t valence_perf_measured_hz(const struct valence_perf_snapshot *s) {
    return s->window ? (uint64_t)s->delta[0]*s->reference_hz/s->window : 0;
}
#endif
