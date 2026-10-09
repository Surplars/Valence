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
static unsigned char memory[8192],input[16384],output[262144];
static unsigned input_n,input_at,output_n,runs,diagnostics,quiet_calls,net_calls;
static int busy,netbad,corrupt_after_net,dma_busy,probe_char,external_takeover,external_network_started;
static uint32_t expected_crc;
static jmp_buf done;
uint8_t *boot_test_ram(void){return memory;}
uint64_t boot_test_now(void){static uint64_t t;return ++t;}
int boot_test_getc(uint64_t budget){if(!budget){int c=probe_char;probe_char=0;return c?c:-1;}if(input_at==input_n){if(menu_binary)return -1;longjmp(done,1);}return input[input_at++];}
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
void monitor_run_diagnostic(unsigned op,unsigned len){assert(!busy&&!dma_busy);assert(op=='C'||op=='b'||op=='m'||op=='t'||op=='u');assert(len==0||len==16);++diagnostics;}
static int has(const char *s){for(unsigned i=0;i+strlen(s)<=output_n;i++)if(!memcmp(output+i,s,strlen(s)))return 1;return 0;}
static void reset(void){input_n=input_at=output_n=runs=diagnostics=quiet_calls=net_calls=0;busy=netbad=corrupt_after_net=dma_busy=probe_char=external_takeover=external_network_started=0;external_state_untrusted=0;image_valid=image_entry=image_length=image_crc=image_record_crc=image_network=menu_ansi=0;menu_pending=0;uart_prefetched=-1;menu_color=1;menu_selected=menu_escape=menu_escape_bytes=menu_last_cr=menu_escape_timedout=menu_screen=menu_binary=menu_log_pending=0;menu_result="Choose a download; verified images start automatically.";menu_progress_at=0;memset(memory,0,sizeof memory);}
static void commands(const char *s){input_n=strlen(s);memcpy(input,s,input_n);if(!setjmp(done))boot_main();}
static void add32(uint32_t v){for(unsigned b=0;b<4;b++)input[input_n++]=(uint8_t)(v>>(b*8));}
static void uart_session(void){uint8_t bytes[16];for(unsigned i=0;i<16;i++)bytes[i]=(uint8_t)i;input[input_n++]='d';unsigned start=input_n;add32(0x31444c56);add32(1);add32(RAM_BASE);add32(RAM_BASE);add32(16);add32(oracle(bytes,16));add32(256);add32(0);add32(oracle(input+start,32));add32(0x41544144);add32(0);add32(16);add32(oracle(bytes,16));memcpy(input+input_n,bytes,16);input_n+=16;}
static void seed_image(void){image_entry=RAM_BASE;image_length=16;commit_image(oracle(memory,16));}
static void run_commands(void){if(!setjmp(done))boot_main();}
int main(int argc,char **argv){unsigned cases=0;
 if(argc>1){reset();menu_ansi=1;menu_color=1;show_menu();if(!strcmp(argv[1],"--snapshot")){fwrite(output,1,output_n,stdout);return 0;}return 2;}
 reset();commands("h");assert(!net_calls&&!runs&&has("Valence BootROM"));++cases;
 reset();commands("n");assert(net_calls==1&&!image_valid&&runs==1&&has("NETWORK IMAGE VERIFIED")&&has("AUTOBOOT")&&has("APP RETURN"));++cases;
 reset();commands("nvrg4");assert(runs==1&&has("RAM IMAGE VERIFIED")&&has("EXTERNAL STATE LOCKED"));++cases;
 reset();commands("1");assert(runs==1);++cases;
 reset();corrupt_after_net=1;commands("nvr");assert(!runs&&!image_valid&&has("RAM CRC FAIL")&&!has("AUTOBOOT"));++cases;
 reset();commands("rg4");assert(!runs&&has("Manual launch removed"));++cases;
 reset();busy=1;seed_image();commands("ndt");assert(!runs&&!net_calls&&!diagnostics&&!image_valid&&has("DMA BUSY"));++cases;
 reset();dma_busy=1;seed_image();commands("ndt");assert(!runs&&!net_calls&&!diagnostics&&!image_valid&&has("MEMORY DMA BUSY"));++cases;
 reset();netbad=1;seed_image();commands("nr");assert(!runs&&!image_valid);++cases;
 reset();commands("cCbmt");assert(diagnostics==5&&!external_state_untrusted);++cases;
 reset();commands("aki");assert(!menu_ansi&&!menu_color&&has("FW clock_hz"));++cases;
 reset();uart_session();run_commands();assert(runs==1&&!image_valid&&has("VDON")&&has("DOWNLOAD OK")&&has("AUTOBOOT"));++cases;
 reset();seed_image();image_record_crc^=1;launch_downloaded_image();assert(!runs&&!image_valid&&has("NO TRUSTED IMAGE"));++cases;
 reset();seed_image();image_length=IMAGE_LIMIT+1;image_record_crc=image_record_sum();launch_downloaded_image();assert(!runs&&!image_valid);++cases;
 reset();seed_image();image_valid=0;launch_downloaded_image();assert(!runs);++cases;
 reset();probe_char='d';commands("n");assert(!runs&&!image_valid&&has("VERIFY CANCELLED")&&has("VLOAD1"));++cases;
 reset();probe_char=27;commands("n");assert(!runs&&!image_valid&&has("VERIFY CANCELLED"));++cases;
 reset();seed_image();image_entry++;image_record_crc=image_record_sum();launch_downloaded_image();assert(!runs&&!image_valid);++cases;
 reset();external_takeover=1;commands("nndvrgcCbmtu123456789ahi");
 assert(external_network_started&&external_state_untrusted&&runs==1&&net_calls==1&&!diagnostics&&!image_valid);
 assert(has("EXTERNAL STATE LOCKED")&&has("FW clock_hz"));
 for(unsigned i=0;i<16;i++){assert(memory[i]==(uint8_t)(i*17+3));}++cases;
 reset();seed_image();commands("rg4");assert(!runs);++cases;
 reset();seed_image();input[input_n++]='d';run_commands();assert(!runs&&!image_valid&&has("DOWNLOAD ABORT"));++cases;
 reset();uart_session();input[1+32]^=1;run_commands();assert(!runs&&!image_valid&&!has("VDON"));++cases;
 reset();uart_session();--input_n;run_commands();assert(!runs&&!image_valid&&has("DOWNLOAD ABORT"));++cases;
 /* Raw protocol is byte-exact between VLOAD and VDON: no ANSI escapes, nor bar. */
 reset();uart_session();run_commands();
 unsigned first=0,last=0;for(unsigned i=0;i+6<output_n;++i){if(!memcmp(output+i,"VLOAD1",6))first=i;if(!memcmp(output+i,"VDON",4))last=i;}
 assert(last>first);for(unsigned i=first;i<last;++i)assert(output[i]!=27);++cases;
 /* Fragmented VT100 CSI, SS3, bare Escape timeout, malformed input. */
 reset();assert(menu_key(27,0)==MENU_NONE);assert(menu_key('[',1)==MENU_NONE);assert(menu_key('B',2)==MENU_DOWN);++cases;
 assert(menu_key(27,3)==MENU_NONE);assert(menu_key('O',4)==MENU_NONE);assert(menu_key('A',5)==MENU_UP);++cases;
 assert(menu_key(27,6)==MENU_NONE);assert(menu_key(-1,CPU_HZ)==MENU_ESC);assert(menu_key('d',CPU_HZ+1)=='d');++cases;
 assert(menu_key(27,CPU_HZ+2)==MENU_NONE);assert(menu_key('[',CPU_HZ+3)==MENU_NONE);assert(menu_key('1',CPU_HZ+4)==MENU_NONE);assert(menu_key(';',CPU_HZ+5)==MENU_NONE);assert(menu_key('5',CPU_HZ+6)==MENU_NONE);assert(menu_key('A',CPU_HZ+7)==MENU_UP);++cases;
 assert(menu_key(27,CPU_HZ+8)==MENU_NONE);assert(menu_key('d',CPU_HZ+9)==MENU_NONE);assert(menu_key('X',CPU_HZ+10)=='X');++cases;
 reset();commands("\033[B\033[A\r");assert(runs==1&&net_calls==1);++cases;
 reset();commands("\033[9~h");assert(!runs&&!net_calls);++cases;
 reset();menu_ansi=1;menu_binary=1;tui_progress(1,1);assert(!output_n);menu_binary=0;tui_progress(1,100);assert(!output_n);tui_progress(100,100);assert(has("100%"));++cases;
 reset();commands("\033[B\033[B\033[B\r\n");assert(diagnostics==1&&!runs&&!net_calls);++cases;
 reset();assert(menu_key(27,0)==MENU_NONE);assert(menu_key('[',1)==MENU_NONE);for(unsigned i=0;i<20;++i)assert(menu_key('1',2+i)==MENU_NONE);assert(menu_key('d',22)==MENU_NONE);assert(menu_key('h',23)=='h');++cases;
 reset();commands("\033[2$d\033]ndjc\007h");assert(!net_calls&&!runs&&!diagnostics&&!has("VLOAD1"));++cases;
 reset();commands("\033Pndjc\033\\h");assert(!net_calls&&!runs&&!diagnostics&&!has("VLOAD1"));++cases;
 reset();uart_session();memmove(input+5,input+1,input_n-1);memcpy(input,"\033[B\r\n",5);input_n+=4;run_commands();assert(runs==1&&has("VDON"));++cases;
 reset();uart_session();memmove(input+5,input,input_n);memcpy(input,"\033[B\r\n",5);input_n+=5;run_commands();assert(runs==1&&has("VDON"));++cases;
 reset();probe_char=27;commands("n[5~h");assert(!runs&&!diagnostics&&!image_valid);++cases;
 reset();assert(menu_key(27,0)==MENU_NONE);assert(menu_key('[',1)==MENU_NONE);assert(menu_key(-1,CPU_HZ)==MENU_ESC);assert(menu_key(-1,CPU_HZ*2)==MENU_NONE);assert(menu_key('d',CPU_HZ*2+1)==MENU_NONE);assert(menu_key('h',CPU_HZ*2+2)=='h');++cases;
 reset();assert(menu_key(27,0)==MENU_NONE);assert(menu_key(']',1)==MENU_NONE);assert(menu_key('d',2)==MENU_NONE);assert(menu_key(-1,CPU_HZ)==MENU_ESC);assert(menu_key('n',CPU_HZ+1)==MENU_NONE);assert(menu_key(3,CPU_HZ+2)==MENU_ESC);assert(menu_key('h',CPU_HZ+3)=='h');assert(menu_key('d',CPU_HZ+4)=='d');++cases;
 reset();commands("\033]unterminated\003hd");assert(!runs&&!net_calls&&!diagnostics&&has("VLOAD1"));++cases;
 reset();commands("cC5");assert(diagnostics==3&&!runs);++cases;
 reset();commands("u9");assert(diagnostics==2&&!runs&&!external_state_untrusted);++cases;
 reset();busy=1;commands("u9");assert(!diagnostics&&has("DMA BUSY"));++cases;
 reset();dma_busy=1;commands("u9");assert(!diagnostics&&has("MEMORY DMA BUSY"));++cases;
 reset();commands("h");assert(has("u/9  S-mode Bare / Sv39 MMU bandwidth")&&MENU_COUNT<=10);++cases;
 printf("BOOTROM_MENU_PASS cases=%u autostart=1 no_manual_run=1 metadata_crc=1 busy_invalidates=1 binary_no_ansi=1 diagnostic_dispatch_only=1\n",cases);return 0;
}
