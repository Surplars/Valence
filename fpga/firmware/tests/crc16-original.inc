uint32_t firmware_crc_update(uint32_t crc, const uint8_t *p, unsigned n) {
#if FIRMWARE_CRC_MODE == 2
    /* Byte packing is deliberate: callers may pass any alignment, and no read
     * crosses the supplied byte range. Four table dependencies are independent. */
    while(n>=4) {
        uint32_t word=(uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
        crc^=word;
        crc=crc32_table[768+(crc&255)] ^ crc32_table[512+((crc>>8)&255)] ^
            crc32_table[256+((crc>>16)&255)] ^ crc32_table[crc>>24];
        p+=4; n-=4;
    }
#elif FIRMWARE_CRC_MODE == 3
    /* Pack only bytes within the supplied range; preserve arbitrary alignment. */
    while(n>=2) {
        crc^=(uint32_t)p[0] | (uint32_t)p[1]<<8;
        crc=(crc>>16)^crc32_table[256+(crc&255)]^crc32_table[(crc>>8)&255];
        p+=2; n-=2;
    }
#endif
    while(n--) {
        crc^=*p++;
#if FIRMWARE_CRC_MODE == 0
        crc=(crc>>4)^crc32_table[crc&15];
        crc=(crc>>4)^crc32_table[crc&15];
#else
        crc=(crc>>8)^crc32_table[crc&255];
#endif
    }
    return crc;
}
