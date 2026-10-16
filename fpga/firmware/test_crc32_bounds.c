/* Independent raw-bitwise oracle and ASan-poisoned input bounds. */
#include "crc32.h"
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <sanitizer/asan_interface.h>
static uint32_t oracle(uint32_t c,const uint8_t *p,unsigned n) {
    while(n--) { c^=*p++; for(unsigned j=0;j<8;j++) c=(c>>1)^(0xedb88320U&(0U-(c&1))); } return c;
}
static uint32_t state=0x2ab87961;
static uint32_t random32(void) {state^=state<<13;state^=state>>17;state^=state<<5;return state;}
int main(void) {
    unsigned cases=0;
    for(unsigned a=0;a<8;a++) for(unsigned n=0;n<=4097;n++) {
        uint8_t *b=malloc(n+a+32);assert(b);memset(b,0xa5,n+a+32);uint8_t *p=b+16+a;
        for(unsigned i=0;i<n;i++) p[i]=(uint8_t)random32();
        uint32_t seed=random32(),expected=oracle(seed,p,n);unsigned split=n?random32()%(n+1):0;
        __asan_poison_memory_region(p+n,16); /* Tail is poisoned even at odd length/alignment. */
        assert(firmware_crc_update(seed,p,n)==expected);
        assert(firmware_crc_update(firmware_crc_update(seed,p,split),p+split,n-split)==expected);
        __asan_unpoison_memory_region(b,n+a+32);
        for(unsigned i=0;i<16+a;i++) assert(b[i]==0xa5);
        for(unsigned i=0;i<16;i++) assert(p[n+i]==0xa5);
        free(b);cases++;
    }
    printf("CRC_BOUNDS_PASS cases=%u alignments=8 lengths=0..4097 random_seed=1 split=1 canaries=1 ASan_tail=1\n",cases);
}
