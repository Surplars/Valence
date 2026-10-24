#include <stdint.h>
#include "../../../fpga/firmware/crc32.h"
extern void copy_old(volatile uint8_t *,const uint8_t *,unsigned);
extern void copy_new(volatile uint8_t *,const uint8_t *,unsigned);
extern void mark_begin(unsigned),mark_end(unsigned),mark_crc_begin(unsigned),mark_crc_end(unsigned);
extern void perf_fail(void) __attribute__((noreturn));
extern void perf_done(void) __attribute__((noreturn));
void perf_main(void){
    const uint8_t *last=0;
    for(unsigned cfg=2;cfg<12;cfg+=3){
        unsigned kind=cfg/3;
        uintptr_t source=0x80210000UL+cfg*0x1000;
        volatile uint64_t *dest_words=(volatile uint64_t *)(source+0x800);
        const uint8_t *src=(const uint8_t *)(source+6);
        volatile uint8_t *dst=(volatile uint8_t *)(source+0x804);
        void (*fn)(volatile uint8_t *,const uint8_t *,unsigned)=kind&1?copy_new:copy_old;
        if(kind>=2)fn=(void *)((uintptr_t)fn+0x200000);
        __asm__ volatile("fence.i":::"memory");
        volatile uint64_t sum=0;
        for(unsigned i=0;i<24;i++){
            sum+=((const volatile uint64_t *)source)[i];
            dest_words[i]=0xa5a5a5a5a5a5a5a5ULL;
        }
        (void)sum;
        mark_begin(kind);fn(dst,src,128);mark_end(kind);
        last=(const uint8_t *)dst;
    }
    /* Shared production CRC stage, not included in any copy window.
     * The external DDR oracle checks all four copies byte-for-byte after drain. */
    mark_crc_begin(0);
    uint32_t crc=firmware_crc_update(0xffffffffU,last,128)^0xffffffffU;
    mark_crc_end(0);
    if(crc!=CRC6)perf_fail();
    __asm__ volatile("fence.i":::"memory");
    perf_done();
}
