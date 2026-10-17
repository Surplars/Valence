static uint32_t candidate_sum16(uint32_t sum,const uint8_t *p,unsigned n) {
    /* Explicit alias type: byte-backed RX storage may be read as aligned words.
     * Test alignment before the cast/load and never read beyond the byte span. */
#if !defined(__BYTE_ORDER__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error sum16 aligned candidate requires a little-endian target
#endif
    typedef uint16_t checksum_halfword __attribute__((may_alias));
    if(((uintptr_t)p&1U)==0) {
        while(n>=2) {
            uint32_t word=*(const checksum_halfword *)p;
            sum+=((word&255U)<<8)|(word>>8);
            p+=2; n-=2;
        }
    } else {
        while(n>=2) { sum+=be16(p); p+=2; n-=2; }
    }
    if(n) sum+=(uint32_t)*p<<8;
    return sum;
}
