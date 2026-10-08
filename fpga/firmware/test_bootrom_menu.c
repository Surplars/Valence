/* Actual monitor parser with bounded scripted UART and independent image oracle. */
#define BOOTROM_TEST 1
#define BOOT_MENU 1
#define BOARD_NETBOOT 1
#define BOARD_DDR 1
#define BOARD_RAM_BYTES 0x80000000UL
#define BOARD_MONITOR_BASE 0xffff8000UL
#define FIRMWARE_CRC_MODE 1
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "bootrom.c"
static unsigned char memory[8192],input[16384],output[65536];
static unsigned input_n,input_at,output_n,runs,diagnostics,quiet_calls,net_calls;
static int busy,netbad,corrupt_after_net,dma_busy,probe_char,external_takeover,external_network_started;
static uint32_t expected_crc;
static jmp_buf done;
uint8_t *boot_test_ram(void){return memory;}
uint64_t boot_test_now(void){static uint64_t t;return ++t;}
int boot_test_getc(uint64_t budget){if(!budget){int c=probe_char;probe_char=0;return c?c:-1;}if(input_at==input_n)longjmp(done,1);return input[input_at++];}
void boot_test_putc(uint8_t c){assert(output_n<sizeof output);output[output_n++]=c;}
static uint32_t oracle(const uint8_t *p,unsigned n){uint32_t c=~0U;while(n--){c^=*p++;for(unsigned b=0;b<8;b++)c=(c>>1)^((c&1)?0xedb88320U:0);}return ~c;}
int board_netboot(uint32_t *entry,uint32_t *length){++net_calls;if(netbad)return 0;*entry=RAM_BASE;*length=16;for(unsigned i=0;i<16;i++)memory[i]=(uint8_t)(i*17+3);expected_crc=oracle(memory,16);if(corrupt_after_net)memory[5]^=1;return 1;}
uint32_t board_netboot_verified_crc(void){return expected_crc;}
int board_netboot_quiet(void){assert(!external_network_started);++quiet_calls;return !busy;}
int board_netboot_command(void){return 0;}
void board_netboot_jump(uint32_t e,uint32_t n){assert(e==RAM_BASE&&n==16);}
void run_image(uintptr_t e){assert(e==RAM_BASE);assert(external_state_untrusted);++runs;if(external_takeover)external_network_started=1;}
int monitor_memory_dma_idle(void){return !dma_busy;}
int firmware_ram_dma_idle(void){return !dma_busy;}
int firmware_ram_prepare(uint64_t *f,uint64_t *s){*f=1;*s=2;return !dma_busy;}
void monitor_run_diagnostic(unsigned op,unsigned len){assert(!busy&&!dma_busy);assert(op=='c'||op=='C'||op=='b'||op=='m'||op=='t');assert(len==0||len==16);++diagnostics;}
static int has(const char *s){for(unsigned i=0;i+strlen(s)<=output_n;i++)if(!memcmp(output+i,s,strlen(s)))return 1;return 0;}
static void reset(void){input_n=input_at=output_n=runs=diagnostics=quiet_calls=net_calls=0;busy=netbad=corrupt_after_net=dma_busy=probe_char=external_takeover=external_network_started=0;external_state_untrusted=0;image_valid=image_entry=image_length=image_crc=image_record_crc=image_network=menu_ansi=0;menu_pending=0;memset(memory,0,sizeof memory);}
static void commands(const char *s){input_n=strlen(s);memcpy(input,s,input_n);if(!setjmp(done))boot_main();}
static void add32(uint32_t v){for(unsigned b=0;b<4;b++)input[input_n++]=(uint8_t)(v>>(b*8));}
static void uart_session(void){uint8_t bytes[16];for(unsigned i=0;i<16;i++)bytes[i]=(uint8_t)i;input[input_n++]='d';unsigned start=input_n;add32(0x31444c56);add32(1);add32(RAM_BASE);add32(RAM_BASE);add32(16);add32(oracle(bytes,16));add32(256);add32(0);add32(oracle(input+start,32));add32(0x41544144);add32(0);add32(16);add32(oracle(bytes,16));memcpy(input+input_n,bytes,16);input_n+=16;}
int main(void){unsigned cases=0;
 reset();commands("h");assert(!net_calls&&!runs&&has("Valence monitor"));++cases;
 reset();commands("n");assert(net_calls==1&&image_valid&&!runs&&has("NETWORK IMAGE VERIFIED"));++cases;
 reset();commands("nvr");assert(runs==1&&has("RAM IMAGE VERIFIED")&&has("APP RETURN"));++cases;
 reset();commands("1" "3" "4");assert(runs==1);++cases;
 reset();corrupt_after_net=1;commands("nvr");assert(!runs&&!image_valid&&has("RAM CRC FAIL"));++cases;
 reset();commands("r");assert(!runs&&has("NO IMAGE"));++cases;
 reset();busy=1;commands("nrt");assert(!runs&&!net_calls&&!diagnostics&&has("DMA BUSY"));++cases;
 reset();dma_busy=1;commands("nrt");assert(!runs&&!net_calls&&!diagnostics&&has("MEMORY DMA BUSY"));++cases;
 reset();netbad=1;commands("nr");assert(!runs&&!image_valid);++cases;
 reset();commands("cCbmt");assert(diagnostics==5);++cases;
 reset();commands("ai");assert(menu_ansi&&has("\033[2J")&&has("FW clock_hz"));++cases;
 reset();uart_session();input[input_n++]='g';if(!setjmp(done))boot_main();assert(runs==1&&has("VDON")&&has("DOWNLOAD OK"));++cases;
 reset();commands("n");image_record_crc^=1;input_at=0;input_n=1;input[0]='r';if(!setjmp(done))boot_loop();assert(!runs&&!image_valid&&has("NO TRUSTED IMAGE"));++cases;
 reset();commands("n");image_length=IMAGE_LIMIT+1;image_record_crc=image_record_sum();input_at=0;input_n=1;input[0]='r';if(!setjmp(done))boot_loop();assert(!runs&&!image_valid);++cases;
 reset();commands("n");image_valid=0;input_at=0;input_n=1;input[0]='r';if(!setjmp(done))boot_loop();assert(!runs);++cases;
 reset();probe_char='d';commands("nv");assert(!runs&&has("VERIFY CANCELLED")&&has("VLOAD1"));++cases;
 reset();commands("n");image_entry++;image_record_crc=image_record_sum();input_at=0;input_n=1;input[0]='r';if(!setjmp(done))boot_loop();assert(!runs&&!image_valid);++cases;
 reset();external_takeover=1;commands("nrndvrgcCbmt12345678ahi");
 assert(external_network_started&&external_state_untrusted&&runs==1&&net_calls==1&&!diagnostics&&!image_valid);
 assert(has("EXTERNAL STATE LOCKED")&&has("read-only info")&&has("FW clock_hz"));
 for(unsigned i=0;i<16;i++)assert(memory[i]==(uint8_t)(i*17+3));++cases;
 reset();commands("cCbmt");assert(!external_state_untrusted&&diagnostics==5);++cases;
 printf("BOOTROM_MENU_PASS cases=%u manual_network=1 run_recrc=1 metadata_crc=1 busy_pinned=1 uart_g_compatible=1 diagnostic_dispatch_only=1\n",cases);return 0;
}
