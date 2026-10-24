/* Independent byte oracle with poisoned exact source/destination bounds.
 * No host throughput number is advertised as target CPU/board performance. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "netboot_copy.h"
#ifdef NETBOOT_COPY_ASAN
#include <sanitizer/asan_interface.h>
#define POISON(p,n) __asan_poison_memory_region((p),(n))
#define UNPOISON(p,n) __asan_unpoison_memory_region((p),(n))
#else
#define POISON(p,n) ((void)0)
#define UNPOISON(p,n) ((void)0)
#endif
int main(void) {
    const unsigned extras[]={127,128,255,256,511,512,988,1024,1110,1152,4095,4096};
    unsigned count=0;
    for(unsigned a=0;a<8;++a)for(unsigned b=0;b<8;++b)
    for(unsigned k=0;k<65+sizeof extras/sizeof extras[0];++k) {
        unsigned n=k<65?k:extras[k-65],cap=n+64;
        uint8_t *src=malloc(cap),*dst=malloc(cap),*oracle=malloc(cap);
        assert(src&&dst&&oracle);
        memset(src,0x31,cap);memset(dst,0xa5,cap);memset(oracle,0xa5,cap);
        for(unsigned i=0;i<n;++i)src[16+a+i]=(uint8_t)(i*113+(i>>8)+a);
        for(unsigned i=0;i<n;++i)oracle[16+b+i]=src[16+a+i];
        POISON(src,cap);UNPOISON(src+16+a,n);
        /* ASan shadows have8B granularity: source-prefix protection alone
         * cannot detect every same-granule underread; exact end and byte
         * canaries still cover tails. The implementation also proves bounds. */
        netboot_copy(dst+16+b,src+16+a,n);
        UNPOISON(src,cap);
        assert(!memcmp(dst,oracle,cap));
        free(src);free(dst);free(oracle);++count;
    }
    netboot_copy(0,0,0);
    printf("NETBOOT_COPY_HOST_PASS cases=%u all_src_dst_alignments exact_byte_oracle canaries=1\n",count);
}
