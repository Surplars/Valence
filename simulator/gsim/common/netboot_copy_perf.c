#include <stdint.h>
#include "../../../fpga/firmware/netboot_copy.h"
/* Frozen pre-be875ac byte-pack algorithm, excluding its unchanged bounds check. */
__attribute__((noinline)) void copy_old(volatile uint8_t *to,const uint8_t *p,unsigned n){
    typedef uint64_t ram_word __attribute__((may_alias));
    while(n && ((uintptr_t)to&7)){*to++=*p++;--n;}
    while(n>=8){
        uint64_t word=(uint64_t)p[0]|(uint64_t)p[1]<<8|(uint64_t)p[2]<<16|
          (uint64_t)p[3]<<24|(uint64_t)p[4]<<32|(uint64_t)p[5]<<40|
          (uint64_t)p[6]<<48|(uint64_t)p[7]<<56;
        *(volatile ram_word *)to=word;to+=8;p+=8;n-=8;
    }
    while(n--)*to++=*p++;
}
__attribute__((noinline)) void copy_new(volatile uint8_t *to,const uint8_t *p,unsigned n){netboot_copy(to,p,n);}
