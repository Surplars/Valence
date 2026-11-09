#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sanitizer/asan_interface.h>
static uint16_t be16(const uint8_t *p) { return (uint16_t)p[0] << 8 | p[1]; }
#include "sum16-original.inc"
#include "sum16-candidate.inc"
static unsigned long cases,chains;
static void compare(uint32_t initial,const uint8_t *p,unsigned n,unsigned pattern,unsigned alignment) {
    uint32_t a=reference_sum16(initial,p,n),b=candidate_sum16(initial,p,n);
#ifdef ORACLE_NEGATIVE
    if(n==2 && alignment==0 && pattern==0)b^=1U;
#endif
    if(a!=b) {fprintf(stderr,"SUM16_MISMATCH pattern=%u alignment=%u length=%u initial=%08x reference=%08x candidate=%08x\n",pattern,alignment,n,initial,a,b);exit(1);}
    ++cases;
}
int main(void) {
    void *allocation=0;
    if(posix_memalign(&allocation,16,2080))return 2;
    uint8_t *storage=allocation;
    const uint32_t initials[]={0,1,0xffff,0x10000,0x7fffffff,0xffff0000,0xffffffff};
    for(unsigned pattern=0;pattern<4;++pattern) {
        for(unsigned i=0;i<2080;++i)storage[i]=pattern==0?0:pattern==1?255:pattern==2?(uint8_t)i:(uint8_t)((i*73U)^(i>>3)^0xa5U);
        for(unsigned alignment=0;alignment<8;++alignment)for(unsigned n=0;n<=2048;++n) {
            uint8_t *p=storage+alignment;
            __asan_poison_memory_region(storage,2080);
            __asan_unpoison_memory_region(p,n);
            for(unsigned j=0;j<sizeof initials/sizeof initials[0];++j)compare(initials[j],p,n,pattern,alignment);
            /* Differential chaining preserves the exact reference API, including
             * odd splits; it does not redefine odd scatter/gather checksum rules. */
            for(unsigned k=0;k<3;++k) {
                unsigned split=k==0?0:k==1?n/2:n;
                uint32_t a=reference_sum16(reference_sum16(0xfffffff0U,p,split),p+split,n-split);
                uint32_t b=candidate_sum16(candidate_sum16(0xfffffff0U,p,split),p+split,n-split);
                if(a!=b){fprintf(stderr,"SUM16_CHAIN_MISMATCH alignment=%u length=%u split=%u\n",alignment,n,split);return 1;}
                ++chains;
            }
            __asan_unpoison_memory_region(storage,2080);
        }
    }
    free(storage);
    printf("PASS_SUM16_ORACLE direct_cases=%lu chained_cases=%lu alignments=8 lengths=0..2048 patterns=4 initial_sums=7 ASan_UBSan=enabled\n",cases,chains);
    return 0;
}
