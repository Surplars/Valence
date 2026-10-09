/* Actual BootROM C over bidirectional pipes. The independent Python side runs
 * the production uploader, including reset_input_buffer/d/readiness ordering. */
#define _POSIX_C_SOURCE 200809L
#define BOOTROM_TEST 1
#define BOOT_MENU 1
#define BOARD_NETBOOT 1
#define BOARD_DDR 1
#define BOARD_RAM_BYTES 0x80000000UL
#define BOARD_MONITOR_BASE 0xffff8000UL
#define FIRMWARE_CRC_MODE 0
#define CPU_HZ 1000000ULL
#include <assert.h>
#include <poll.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include "bootrom.c"
static uint8_t memory[8192];
uint64_t boot_test_now(void){struct timespec t;assert(!clock_gettime(CLOCK_MONOTONIC,&t));return (uint64_t)t.tv_sec*CPU_HZ+t.tv_nsec/1000;}
uint8_t *boot_test_ram(void){return memory;}
void boot_test_putc(uint8_t c){assert(write(STDOUT_FILENO,&c,1)==1);}
int boot_test_getc(uint64_t budget){
    struct pollfd fd={.fd=STDIN_FILENO,.events=POLLIN};
    int result=poll(&fd,1,(int)((budget+999)/1000));assert(result>=0);
    if(!result)return -1;
    uint8_t c;ssize_t n=read(STDIN_FILENO,&c,1);if(n==0)exit(3);assert(n==1);return c;
}
int firmware_ram_dma_idle(void){return 1;}
int firmware_ram_prepare(uint64_t *a,uint64_t *b){*a=1;*b=2;return 1;}
int monitor_memory_dma_idle(void){return 1;}
void monitor_run_diagnostic(unsigned c,unsigned n){(void)c;(void)n;abort();}
int board_netboot(uint32_t *e,uint32_t *n){(void)e;(void)n;return 0;}
uint32_t board_netboot_verified_crc(void){return 0;}
int board_netboot_quiet(void){return 1;}
int board_netboot_command(void){return 0;}
void board_netboot_jump(uint32_t e,uint32_t n){assert(e==RAM_BASE&&n==769);}
void run_image(uintptr_t e){
    assert(e==RAM_BASE&&!image_valid&&external_state_untrusted);
    for(unsigned i=0;i<769;++i)assert(memory[i]==(uint8_t)(i*37+11));
    puts_uart("GUEST ENTRY SENTINEL\r\n");exit(0);
}
int main(void){boot_main();}
