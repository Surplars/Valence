#define _GNU_SOURCE
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <sanitizer/asan_interface.h>
static uint8_t *destination;
static unsigned image_limit;
#define IMAGE_LIMIT image_limit
static uint8_t *ram_pointer(uint32_t offset) { return destination+offset; }
#include "store16-original.inc"
#include "store16-candidate.inc"
static void die(unsigned sa,unsigned da,unsigned n,const char *why) { fprintf(stderr,"STORE16_MISMATCH source_alignment=%u destination_alignment=%u length=%u reason=%s\n",sa,da,n,why);exit(1); }
static uint8_t pattern(unsigned i,unsigned p) { return p==0?0:p==1?(uint8_t)(i*29+7):(uint8_t)((i*73)^(i>>3)^0xa5); }
int main(void) {
 void *allocation; if(posix_memalign(&allocation,64,16384))return 2;uint8_t *src=allocation;
 uint8_t ref[8192],got[8192],expected[8192];unsigned long cases=0,invalid=0,guards=0;
 image_limit=sizeof got;
 for(unsigned p=0;p<3;p++)for(unsigned sa=0;sa<8;sa++)for(unsigned da=0;da<8;da++)for(unsigned n=0;n<=2048;n++) {
  __asan_unpoison_memory_region(src,16384);for(unsigned i=0;i<n;i++)src[64+sa+i]=pattern(i,p);
  memset(ref,0x69,sizeof ref);memset(got,0x69,sizeof got);memset(expected,0x69,sizeof expected);for(unsigned i=0;i<n;i++)expected[16+da+i]=src[64+sa+i];
  __asan_poison_memory_region(src,64+sa);__asan_poison_memory_region(src+64+sa+n,16384-64-sa-n);
  destination=ref;int a=original_store(NULL,16+da,src+64+sa,n);destination=got;int b=candidate_store(NULL,16+da,src+64+sa,n);
#ifdef ORACLE_NEGATIVE
  if(p==0 && sa==0 && da==0 && n==8)got[16]^=1;
#endif
  if(a||b||memcmp(ref,expected,sizeof ref)||memcmp(got,expected,sizeof got))die(sa,da,n,"bytes");
  cases++;
 }
 __asan_unpoison_memory_region(src,16384);memset(src,0x42,16384);
 const uint32_t offsets[]={8191,8192,8193,UINT32_MAX};const unsigned lengths[]={0,1,2,8192,UINT32_MAX};
 for(unsigned i=0;i<4;i++)for(unsigned j=0;j<5;j++) {
  uint32_t off=offsets[i];unsigned n=lengths[j];int valid=off<=image_limit && n<=image_limit-off;
  memset(ref,0x69,sizeof ref);memset(got,0x69,sizeof got);destination=ref;int a=original_store(NULL,off,src,n);destination=got;int b=candidate_store(NULL,off,src,n);
  if(a!=(valid?0:-1)||b!=a||memcmp(ref,got,sizeof got))die(0,off,n,"range");
  if(!valid) { for(unsigned k=0;k<sizeof got;k++)if(got[k]!=0x69)die(0,off,n,"invalid-write"); }
  invalid++;
 }
 long page=sysconf(_SC_PAGESIZE);if(page<4096)return 3;
 uint8_t *sm=mmap(NULL,page*3,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0),*dm=mmap(NULL,page*3,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);if(sm==MAP_FAILED||dm==MAP_FAILED)return 4;
 if(mprotect(sm+page,page,PROT_READ|PROT_WRITE)||mprotect(dm+page,page,PROT_READ|PROT_WRITE))return 5;
 image_limit=page;destination=dm+page;
 for(unsigned n=0;n<=64;n++)for(unsigned side=0;side<2;side++) {
  uint8_t *p=sm+page+(side?page-n:0);unsigned off=side?page-n:0;
  for(unsigned i=0;i<n;i++)p[i]=pattern(i,2);
  memset(destination,0x69,page);
  if(candidate_store(NULL,off,p,n))die(0,off,n,"guard-return");
  for(unsigned i=0;i<(unsigned)page;i++)if(destination[i]!=(i>=off&&i-off<n?pattern(i-off,2):0x69))die(0,off,n,"guard-bytes");
  guards++;
 }
 munmap(sm,page*3);munmap(dm,page*3);free(src);
 printf("PASS_STORE16_ORACLE cases=%lu range_cases=%lu guard_page_cases=%lu source_alignments=8 destination_alignments=8 lengths=0..2048 patterns=3\n",cases,invalid,guards);return 0;
}
