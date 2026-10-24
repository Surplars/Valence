#ifndef VALENCE_NETBOOT_COPY_H
#define VALENCE_NETBOOT_COPY_H
#include <stdint.h>
#include <stddef.h>

/* Non-overlapping, immutable borrowed RX bytes -> volatile downloaded RAM.
 * Only aligned wide accesses; never read outside [source, source+length).
 * Caller retains DMA completion ownership throughout this copy.
 * This is a candidate ROM optimization, not a board throughput claim. */
static inline void netboot_copy(volatile uint8_t *to,const uint8_t *p,unsigned n) {
    typedef uint64_t alias_word __attribute__((may_alias));
    while(n && ((uintptr_t)to&7)) { *to++=*p++; --n; }
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    if(!((uintptr_t)p&7)) {
        while(n>=8) {
            *(volatile alias_word *)to=*(const alias_word *)p;
            to+=8;p+=8;n-=8;
        }
    } else if(n>=16) {
        /* Consume one word bytewise first. The rounded-down address for the
         * next word then lies inside the original source, not before it. */
        uint64_t word=0;
        for(unsigned i=0;i<8;++i) word|=(uint64_t)p[i]<<(8*i);
        *(volatile alias_word *)to=word;to+=8;p+=8;n-=8;
        unsigned offset=(unsigned)((uintptr_t)p&7), shift=offset*8;
        if(n>=16-offset) {
            const alias_word *aligned=(const alias_word *)(p-offset);
            uint64_t left=*aligned++;
            do {
                uint64_t right=*aligned++;
                *(volatile alias_word *)to=(left>>shift)|(right<<(64-shift));
                left=right;to+=8;p+=8;n-=8;
            } while(n>=16-offset);
        }
    }
#endif
    /* Short/unaligned boundary words use only supplied bytes. */
    while(n>=8) {
        uint64_t word=(uint64_t)p[0] | (uint64_t)p[1]<<8 | (uint64_t)p[2]<<16 |
            (uint64_t)p[3]<<24 | (uint64_t)p[4]<<32 | (uint64_t)p[5]<<40 |
            (uint64_t)p[6]<<48 | (uint64_t)p[7]<<56;
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        *(volatile alias_word *)to=word;
#else
        for(unsigned i=0;i<8;++i)to[i]=(uint8_t)(word>>(i*8));
#endif
        to+=8;p+=8;n-=8;
    }
    while(n--) *to++=*p++;
}
#endif
