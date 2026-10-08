/* Test ROM: actual ROM-resident production CRC, RAM table, no timed UART.
 * Cold = 64 KiB direct-mapped-index eviction sweep, not a cache-invalid CSR.
 * Guest rdtime includes fence before each marker. Host can also observe markers.
 */
#include <stdint.h>
#include "crc32.h"
#ifndef FIRMWARE_CRC_MODE
#define FIRMWARE_CRC_MODE 0
#endif
#define SOURCE ((volatile uint8_t *)0x80400000UL)
#define DEST ((volatile uint8_t *)0x80420000UL)
#define EVICT ((volatile uint64_t *)0x80800000UL)
#define ROWS ((volatile uint64_t *)0x80600000UL)
static volatile uint64_t sink;
static uint64_t ticks(void) {uint64_t t; __asm__ volatile("fence rw,rw\nrdtime %0":"=r"(t)::"memory");return t;}
static void put(const char *s) {volatile uint8_t *u=(volatile uint8_t *)0x10000000UL;while(*s){while(!(u[5]&32)){}u[0]=(uint8_t)*s++;}}
static void cold(void) {uint64_t v=0;for(unsigned i=0;i<8192;i+=8)v^=EVICT[i];sink=v;}
static uint32_t reference(const volatile uint8_t *p,unsigned n) {uint32_t c=~0U;while(n--){c^=*p++;for(unsigned b=0;b<8;b++)c=(c>>1)^(0xedb88320U&(0U-(c&1)));}return ~c;}
void boot_recover(uint64_t cause,uint64_t pc) {(void)cause;(void)pc;put("CRC_BENCH FAIL trap\r\n");for(;;){}}
void boot_main(void) {
 volatile uint8_t *u=(volatile uint8_t *)0x10000000UL;
 while(!(u[5]&64)){}u[3]=0x83;u[0]=1;u[1]=0;u[3]=3;u[1]=0;u[2]=7;
 for(unsigned i=0;i<1032;i++)SOURCE[i]=(uint8_t)(i*73U+(i>>3)+19U);
 for(unsigned i=0;i<8192;i+=8)EVICT[i]=i;
 unsigned row=0;
 for(unsigned warm=0;warm<2;warm++)for(unsigned align=0;align<8;align++,row++) {
   for(unsigned i=0;i<1024;i++)DEST[align+i]=SOURCE[align+i];
   uint32_t expected=reference(SOURCE+align,1024);
   if(warm)sink=firmware_crc_update(~0U,(const void *)(SOURCE+align),1024);else cold();
   uint64_t a=ticks();
   __asm__ volatile(".global crc_stream_start\ncrc_stream_start:":::"memory");
   uint32_t stream=~firmware_crc_update(~0U,(const void *)(SOURCE+align),1024);
   __asm__ volatile(".global crc_stream_stop\ncrc_stream_stop:":::"memory");
   uint64_t b=ticks();
   if(warm)sink=firmware_crc_update(~0U,(const void *)(DEST+align),1024);else cold();
   uint64_t c=ticks();
   __asm__ volatile(".global crc_ram_start\ncrc_ram_start:":::"memory");
   uint32_t ram=~firmware_crc_update(~0U,(const void *)(DEST+align),1024);
   __asm__ volatile(".global crc_ram_stop\ncrc_ram_stop:":::"memory");
   uint64_t d=ticks();
   volatile uint64_t *r=ROWS+row*8;
   r[0]=FIRMWARE_CRC_MODE;r[1]=align;r[2]=warm;r[3]=b-a;r[4]=d-c;r[5]=stream;r[6]=ram;r[7]=1024;
   if(stream!=expected||ram!=expected||!r[3]||!r[4]){put("CRC_BENCH FAIL crc\r\n");for(;;){}}
 }
 __asm__ volatile("fence rw,rw\nfence.i\nfence rw,rw":::"memory");
 put("CRC_BENCH PASS\r\n");for(;;){}
}
