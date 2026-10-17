static int original_store(void *unused,uint32_t offset,const uint8_t *p,unsigned n) {
    (void)unused;
    if(offset>IMAGE_LIMIT || n>IMAGE_LIMIT-offset) return -1;
    volatile uint8_t *to=ram_pointer(offset);
    /* Frame payload alignment is arbitrary. Pack from bytes, and issue only
     * aligned wide RAM stores; prefix/tail stores preserve neighboring bytes.
     * may_alias also keeps the native byte-array oracle well-defined. */
    typedef uint64_t ram_word __attribute__((may_alias));
    while(n && ((uintptr_t)to&7)) { *to++=*p++; --n; }
    while(n>=8) {
        uint64_t word=(uint64_t)p[0] | (uint64_t)p[1]<<8 | (uint64_t)p[2]<<16 |
            (uint64_t)p[3]<<24 | (uint64_t)p[4]<<32 | (uint64_t)p[5]<<40 |
            (uint64_t)p[6]<<48 | (uint64_t)p[7]<<56;
        *(volatile ram_word *)to=word; to+=8; p+=8; n-=8;
    }
    while(n--) *to++=*p++;
    return 0;
}
