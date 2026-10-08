#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "valence_media_policy.h"
int main(void) {
    unsigned cases=0;
    for(unsigned version=0;version<3;++version)
    for(unsigned requested=0;requested<4;++requested)
    for(unsigned applied=0;applied<4;++applied)
    for(unsigned flags=0;flags<8;++flags)
    for(unsigned fault=0;fault<16;++fault)
    for(unsigned pending=0;pending<4;++pending) {
        uint64_t status=(uint64_t)version<<56 | (uint64_t)fault<<8 | pending<<6 |
            applied<<4 | requested<<2 | (flags&3) | ((flags&4)?0x1000:0);
        unsigned expected=version==1&&requested==applied&&applied<3&&flags==7&&!fault&&!pending ?
            (applied==0?10:applied==1?100:1000):0;
        assert(vg_managed_media_speed(status)==expected);++cases;
    }
    printf("MANAGED_MEDIA_POLICY_PASS cases=%u rates=3 unknown_version_rejected=1 pending_fault_mismatch_rejected=1\n",cases);
    return 0;
}
