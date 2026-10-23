#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "valence_clock.h"
static uint64_t registers[16];
static unsigned writes,mode,reads;
static uint64_t rd(void *p,uint64_t addr) {
    (void)p;++reads;
    unsigned off=(unsigned)(addr-VALENCE_RATE_CPU)/8;
    if(mode && writes>=2 && off==RATE_STATUS/8) {
        registers[RATE_STATUS/8]=RATE_PRESENT|RATE_VALID|(mode==1?RATE_SUCCESS:0);
        if(mode==3)registers[RATE_ERRORS/8]=1U<<7;
        registers[RATE_COMPLETED/8]=1;
        registers[RATE_CONFIGURED/8]=mode==1?registers[0]:50000000;
    }
    return registers[off];
}
static void wr(void *p,uint64_t addr,uint64_t value) {
    (void)p;++writes;unsigned off=(unsigned)(addr-VALENCE_RATE_CPU)/8;
    if(off==RATE_ERRORS/8)registers[off]&=~value;else registers[off]=value;
}
static void setup(void) {
    memset(registers,0,sizeof(registers));writes=reads=mode=0;
    registers[RATE_ID/8]=UINT64_C(0x4352000300000002);
    registers[RATE_ADMISSION/8]=0x30;registers[RATE_CAPS/8]=UINT64_C(0x000080033e200a0a);registers[RATE_REFERENCE/8]=250000000;
    registers[RATE_STATUS/8]=RATE_PRESENT|RATE_VALID;
    registers[RATE_MIN/8]=10000000;registers[RATE_MAX/8]=300000000;
}
int main(void) {
    const struct valence_clock_io io={0,rd,wr};
    for(unsigned hz=10000000;hz<=300000000;hz+=5000000) {
        uint32_t p=valence_clock_parameters(hz);
        assert(p && (p&255)==10);
        unsigned m=(p>>8)&255,o=(p>>16)&255;
        assert(m>=32 && m<=62 && o>=3 && o<=128);
        assert(UINT64_C(25000000)*m==(uint64_t)hz*o);
    }
    for(unsigned mhz=50;mhz<=150;mhz+=5) {
        unsigned o=mhz<=75?20:10,m=mhz*o/25;
        assert(valence_clock_parameters(mhz*1000000U)==(10|(m<<8)|(o<<16)));
    }
    assert(valence_clock_parameters(50000000U)==0x14280a);
    assert(valence_clock_parameters(11718750U));
    assert(!valence_clock_parameters(123456789));assert(!valence_clock_parameters(0));
    assert(!valence_clock_parameters(300000001));
    setup();mode=1;assert(valence_rate_set(&io,VALENCE_RATE_CPU,75000000,10)==RATE_OK);
    assert(writes==2 && registers[RATE_PARAMETERS/8]==valence_clock_parameters(75000000));
    setup();assert(valence_rate_set(&io,VALENCE_RATE_CPU,75000000,3)==RATE_POLL_TIMEOUT);
    assert(reads<30);
    setup();registers[RATE_STATUS/8]|=RATE_BUSY;
    assert(valence_rate_set(&io,VALENCE_RATE_CPU,75000000,3)==RATE_NOT_READY && !writes);
    setup();registers[RATE_ID/8]=1;
    assert(valence_rate_set(&io,VALENCE_RATE_CPU,75000000,3)==RATE_BAD_ABI && !writes);
    setup();registers[RATE_MAX/8]=250000000;
    assert(valence_rate_set(&io,VALENCE_RATE_CPU,300000000,3)==RATE_BAD_FREQUENCY && !writes);
    setup();registers[RATE_ERRORS/8]=8;mode=1;
    assert(valence_rate_set(&io,VALENCE_RATE_CPU,50000000,3)==RATE_OK && writes==3);
    setup();mode=2;assert(valence_rate_set(&io,VALENCE_RATE_CPU,75000000,3)==RATE_FAILED);
    assert(registers[RATE_CONFIGURED/8]==50000000 && writes==2); /* fallback is NOT requested success */
    setup();mode=3;assert(valence_rate_set(&io,VALENCE_RATE_CPU,75000000,3)==RATE_FAILED);
    assert(registers[RATE_ERRORS/8]==(1U<<7) && writes==2); /* preserve lock failure evidence */
    setup();registers[RATE_ADMISSION/8]=0;assert(valence_rate_set(&io,VALENCE_RATE_CPU,50000000,3)==RATE_NOT_ADMITTED && !writes);
    puts("VALENCE_CLOCK_PASS exact_grid_59 success busy bad_abi bound timeout w1c fallback lock_error");
}
