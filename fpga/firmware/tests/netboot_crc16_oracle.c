#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sanitizer/asan_interface.h>
uint32_t reference_crc_update(uint32_t,const uint8_t*,unsigned);
uint32_t candidate_crc_update(uint32_t,const uint8_t*,unsigned);
static unsigned long direct_cases,chained_cases;
static uint32_t bitwise(uint32_t crc,const uint8_t *p,unsigned n) {
    while(n--) { crc^=*p++; for(unsigned j=0;j<8;++j)crc=(crc>>1)^(0xedb88320U & (0U-(crc&1U))); }
    return crc;
}
static void test(uint32_t initial,const uint8_t *p,unsigned n,unsigned alignment,unsigned pattern) {
    uint32_t a=reference_crc_update(initial,p,n),b=candidate_crc_update(initial,p,n),c=bitwise(initial,p,n);
#ifdef ORACLE_NEGATIVE
    if(n==2 && alignment==0 && pattern==0)b^=1U;
#endif
    if(a!=b || a!=c) {fprintf(stderr,"CRC16_MISMATCH pattern=%u alignment=%u length=%u initial=%08x reference=%08x candidate=%08x bitwise=%08x\n",pattern,alignment,n,initial,a,b,c);exit(1);}
    ++direct_cases;
    unsigned split=n/2;
    uint32_t d=candidate_crc_update(candidate_crc_update(initial,p,split),p+split,n-split);
    if(d!=c){fprintf(stderr,"CRC16_CHAIN_MISMATCH alignment=%u length=%u split=%u\n",alignment,n,split);exit(1);}
    ++chained_cases;
}
int main(void) {
    static const uint8_t vector[]="123456789";
    if((candidate_crc_update(0xffffffffU,vector,9)^0xffffffffU)!=0xcbf43926U || candidate_crc_update(0xffffffffU,vector,0)!=0xffffffffU)return 2;
    void *allocation=0;if(posix_memalign(&allocation,16,16416))return 2;uint8_t *storage=allocation;
    const uint32_t initial[]={0,1,0xffffffffU,0x12345678U,0xffff0000U};
    const unsigned boundary[]={4095,4096,4097,16383,16384};
    for(unsigned pattern=0;pattern<4;++pattern) {
        for(unsigned i=0;i<16416;++i)storage[i]=pattern==0?0:pattern==1?255:pattern==2?(uint8_t)i:(uint8_t)((i*73U)^(i>>3)^0xa5U);
        for(unsigned alignment=0;alignment<8;++alignment)for(unsigned index=0;index<2054;++index) {
            unsigned n=index<=2048?index:boundary[index-2049];uint8_t *p=storage+alignment;
            __asan_poison_memory_region(storage,16416);__asan_unpoison_memory_region(p,n);
            for(unsigned j=0;j<sizeof initial/sizeof initial[0];++j)test(initial[j],p,n,alignment,pattern);
            /* Additional zero/end splits and a one-byte split exercise chaining
             * across odd boundaries independently of the paired-loop alignment. */
            unsigned splits[]={0,1,n};
            for(unsigned k=0;k<3;++k) {
                unsigned split=splits[k];if(split>n)continue;
                uint32_t x=candidate_crc_update(candidate_crc_update(0xffffffffU,p,split),p+split,n-split);
                if(x!=bitwise(0xffffffffU,p,n))return 3;
                ++chained_cases;
            }
            __asan_unpoison_memory_region(storage,16416);
        }
    }
    free(storage);
    printf("PASS_CRC16_ORACLE direct_cases=%lu chained_cases=%lu alignments=8 lengths=0..2048+5boundaries patterns=4 initial_crc=5 independent_bitwise=all known_vector=CBF43926\n",direct_cases,chained_cases);
    return 0;
}
