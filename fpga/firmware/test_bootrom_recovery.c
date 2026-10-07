/* Run real monitor download/command code with scripted UART and board preflight.
 * This proves software dispatch/CRC rejection, not MAC/CDC/DDR behavior. */
#define BOOTROM_TEST 1
#define BOARD_NETBOOT 1
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "bootrom.c"
static uint8_t memory[16384], input[32768], output[32768];
static unsigned in_size,in_pos,out_size,ran,quiet_calls,jumps;
static int pending,unsafe,corrupt_ram;
static unsigned test_length=16, corrupt_offset;
static uint64_t ticks;
static jmp_buf escaped;
uint8_t *boot_test_ram(void) { return memory; }
uint64_t boot_test_now(void) { return ++ticks; }
int boot_test_getc(uint64_t budget) {
    (void)budget;
    if(in_pos==in_size) longjmp(escaped,2);
    return input[in_pos++];
}
void boot_test_putc(uint8_t c) {
    assert(out_size<sizeof output); output[out_size++]=c;
    static const char marker[]="UART stage=ram_crc begin\r\n";
    if(corrupt_ram && out_size>=sizeof(marker)-1 &&
       !memcmp(output+out_size-(sizeof(marker)-1),marker,sizeof(marker)-1)) memory[corrupt_offset]^=1;
}
int board_netboot(uint32_t *entry,uint32_t *length) { (void)entry; (void)length; return 0; }
int board_netboot_quiet(void) { ++quiet_calls; return !unsafe; }
int board_netboot_command(void) { int c=pending; pending=0; return c; }
void board_netboot_jump(uint32_t entry,uint32_t length) { assert(entry==RAM_BASE && length==test_length); ++jumps; }
void run_image(uintptr_t entry) { assert(entry==RAM_BASE); ++ran; longjmp(escaped,1); }
static int contains(const char *s) {
    size_t n=strlen(s);
    for(unsigned i=0;i+n<=out_size;++i) if(!memcmp(output+i,s,n)) return 1;
    return 0;
}
static void add32(uint32_t n) { for(unsigned i=0;i<4;++i) input[in_size++]=(uint8_t)(n>>(8*i)); }
static void reset_test(void) {
    memset(memory,0,sizeof memory); in_size=in_pos=out_size=ran=quiet_calls=jumps=0;
    pending=unsafe=corrupt_ram=0; ticks=0;
    image_valid=image_entry=image_length=image_network=0;
}
static uint32_t oracle(const uint8_t *p,unsigned n) {
    uint32_t crc=~0U;
    while(n--) { crc^=*p++; for(unsigned b=0;b<8;++b) crc=(crc>>1)^(0xedb88320U&(0U-(crc&1))); }
    return ~crc;
}
static void session(int type_command,int bad_stream) {
    uint8_t data[8193]; for(unsigned i=0;i<test_length;++i) data[i]=(uint8_t)(i*13+1);
    if(type_command) input[in_size++]='d';
    unsigned header_start=in_size;
    add32(0x31444c56); add32(1); add32(RAM_BASE); add32(RAM_BASE);
    add32(test_length); add32(oracle(data,test_length)^(unsigned)bad_stream); add32(256); add32(0);
    add32(oracle(input+header_start,32));
    for(unsigned off=0,seq=0;off<test_length;++seq) {
        unsigned n=test_length-off>256?256:test_length-off;
        add32(0x41544144); add32(seq); add32(n); add32(oracle(data+off,n));
        memcpy(input+in_size,data+off,n); in_size+=n; off+=n;
    }
    input[in_size++]='g';
}
static int run_loop(void) {
    int result=setjmp(escaped);
    if(!result) boot_loop();
    return result;
}
int main(void) {
    unsigned cases=0;
    reset_test(); session(1,0);
    assert(run_loop()==1 && ran==1 && jumps==1 && quiet_calls==1);
    assert(contains("VDON") && contains("DOWNLOAD OK") && contains("ready to boot")); ++cases;
    reset_test(); assert(!network_download()); session(1,0);
    assert(run_loop()==1 && ran==1 && !image_network);
    assert(contains("UART recovery") && contains("VDON")); ++cases;
    reset_test(); assert(!network_download()); pending='d'; session(0,0);
    assert(run_loop()==1 && ran==1 && !pending); ++cases;
    reset_test(); unsafe=1; session(1,0);
    assert(run_loop()==2 && !ran && !jumps && quiet_calls==1 && image_valid);
    assert(contains("DMA BUSY; RESET REQUIRED"));
    unsafe=0; input[in_size++]='g';
    assert(run_loop()==1 && ran==1 && quiet_calls==2); ++cases;
    reset_test(); session(1,1);
    assert(run_loop()==2 && !ran && !image_valid && !quiet_calls);
    assert(contains("IMAGE CRC FAIL") && contains("NO IMAGE") && !contains("VDON")); ++cases;
    reset_test(); corrupt_ram=1; session(1,0);
    assert(run_loop()==2 && !ran && !image_valid && !quiet_calls);
    assert(contains("RAM CRC FAIL") && contains("NO IMAGE") && !contains("VDON")); ++cases;
    test_length=8193;
    const unsigned offsets[]={0,255,256,4095,4096,8192};
    for(unsigned epoch=0;epoch<2;++epoch) {
        reset_test(); session(1,0);
        assert(run_loop()==1 && ran==1 && jumps==1); ++cases;
        for(unsigned i=0;i<sizeof offsets/sizeof offsets[0];++i) {
            reset_test(); corrupt_ram=1; corrupt_offset=offsets[i]; session(1,0);
            assert(run_loop()==2 && !ran && !jumps && !image_valid);
            assert(contains("RAM CRC FAIL") && contains("NO IMAGE") && !contains("VDON")); ++cases;
        }
    }
    printf("BOOTROM_UART_RECOVERY_PASS cases=%u netfail_uart_run=1 cancel_uart_run=1 verified_run=1 busy_blocks_run=1 stream_crc_negative=1 ram_crc_negative=1 rtl_proof=0\n",cases);
    return 0;
}
