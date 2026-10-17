static int candidate_store(void *unused,uint32_t offset,const uint8_t *p,unsigned n) {
    (void)unused;
    if(offset>IMAGE_LIMIT || n>IMAGE_LIMIT-offset) return -1;
    volatile uint8_t *to=ram_pointer(offset);
    /* Frame payload alignment is arbitrary. Pack from bytes, and issue only
     * aligned wide RAM stores; prefix/tail stores preserve neighboring bytes.
     * may_alias also keeps the native byte-array oracle well-defined. */
    typedef uint64_t ram_word __attribute__((may_alias));
    while(n && ((uintptr_t)to&7)) { *to++=*p++; --n; }
#if !defined(__BYTE_ORDER__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error aligned RAM packing requires a little-endian target
#endif
    typedef uint16_t source_halfword __attribute__((may_alias));
    if(((uintptr_t)p&1U)==0) {
        while(n>=8) {
            uint64_t word=(uint64_t)*(const source_halfword *)(p+0) |
                (uint64_t)*(const source_halfword *)(p+2)<<16 |
                (uint64_t)*(const source_halfword *)(p+4)<<32 |
                (uint64_t)*(const source_halfword *)(p+6)<<48;
            *(volatile ram_word *)to=word; to+=8; p+=8; n-=8;
        }
    } else {
        while(n>=8) {
            uint64_t word=(uint64_t)p[0] | (uint64_t)p[1]<<8 | (uint64_t)p[2]<<16 |
                (uint64_t)p[3]<<24 | (uint64_t)p[4]<<32 | (uint64_t)p[5]<<40 |
                (uint64_t)p[6]<<48 | (uint64_t)p[7]<<56;
            *(volatile ram_word *)to=word; to+=8; p+=8; n-=8;
        }
    }
    while(n--) *to++=*p++;
    return 0;
}
