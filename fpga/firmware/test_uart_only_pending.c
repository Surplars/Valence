#define BOOTROM_TEST 1
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "bootrom.c"
static uint8_t memory[64];static char output[4096];static unsigned at,runs;static int probe;
static jmp_buf escape;
uint64_t boot_test_now(void){static uint64_t t;return ++t;}
uint8_t *boot_test_ram(void){return memory;}
void boot_test_putc(uint8_t c){assert(at<sizeof output-1);output[at++]=c;}
int boot_test_getc(uint64_t budget){if(!budget){int c=probe;probe=0;return c?c:-1;}longjmp(escape,1);}
int firmware_ram_dma_idle(void){return 1;}
int firmware_ram_prepare(uint64_t *f,uint64_t *s){*f=1;*s=2;return 1;}
void run_image(uintptr_t entry){assert(entry==RAM_BASE);++runs;longjmp(escape,2);}
int main(void){image_entry=RAM_BASE;image_length=16;legacy_commit(crc32(memory,16));probe='d';
 assert(!legacy_verify_run()&&legacy_pending=='d');if(!setjmp(escape))boot_loop();assert(strstr(output,"VLOAD1")&&!image_valid&&!runs);
 image_entry=RAM_BASE;image_length=16;legacy_commit(crc32(memory,16));legacy_pending='g';if(!setjmp(escape))boot_loop();assert(!runs);
 puts("UART_ONLY_PENDING_PASS cases=2 verify_cancel_to_download=1 queued_g_cannot_launch=1");return 0;}
