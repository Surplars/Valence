/* Run real monitor download/command code with scripted UART and board preflight.
 * This proves software dispatch/CRC rejection, not MAC/CDC/DDR behavior. */
#define BOOTROM_TEST 1
#define BOARD_NETBOOT 1
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "bootrom.c"
static int memory_dma_busy;
int firmware_ram_dma_idle(void){return !memory_dma_busy;}
int firmware_ram_prepare(uint64_t *f,uint64_t *s){*f=1;*s=2;return 1;}
static uint8_t memory[16384], input[32768], output[32768];
static unsigned in_size,in_pos,out_size,ran,quiet_calls,jumps;
static int pending,unsafe,corrupt_ram,external_takeover,external_network_started,corrupt_after_done;
static unsigned deny_quiet_from;
static unsigned test_length=16, corrupt_offset;
static int network_success,network_corrupt;
static uint32_t network_crc;
static uint64_t ticks;
static jmp_buf escaped;
uint8_t *boot_test_ram(void) { return memory; }
uint64_t boot_test_now(void) { return ++ticks; }
int boot_test_getc(uint64_t budget) {
    if(!budget)return -1;
    if(in_pos==in_size) longjmp(escaped,2);
    return input[in_pos++];
}
void boot_test_putc(uint8_t c) {
    assert(out_size<sizeof output); output[out_size++]=c;
    static const char marker[]="UART stage=ram_crc begin\r\n";
    if(corrupt_after_done && out_size>=13 && !memcmp(output+out_size-13,"DOWNLOAD OK\r\n",13)) memory[5]^=1;
    if(corrupt_ram && out_size>=sizeof(marker)-1 &&
       !memcmp(output+out_size-(sizeof(marker)-1),marker,sizeof(marker)-1)) memory[corrupt_offset]^=1;
}
int board_netboot(uint32_t *entry,uint32_t *length) {
    if(!network_success)return 0;
    *entry=RAM_BASE;*length=test_length;
    for(unsigned i=0;i<test_length;++i)memory[i]=(uint8_t)(i*13+1);
    network_crc=crc32(memory,test_length);
    if(network_corrupt)memory[5]^=1;
    return 1;
}
uint32_t board_netboot_verified_crc(void){return network_crc;}
int board_netboot_quiet(void) { assert(!external_network_started); ++quiet_calls; return !unsafe || quiet_calls<deny_quiet_from; }
int board_netboot_command(void) { int c=pending; pending=0; return c; }
void board_netboot_jump(uint32_t entry,uint32_t length) { assert(entry==RAM_BASE && length==test_length); ++jumps; }
void run_image(uintptr_t entry) { assert(entry==RAM_BASE); ++ran;assert(external_state_untrusted);if(external_takeover){external_network_started=1;return;}longjmp(escaped,1); }
static int contains(const char *s) {
    size_t n=strlen(s);
    for(unsigned i=0;i+n<=out_size;++i) if(!memcmp(output+i,s,n)) return 1;
    return 0;
}
static void add32(uint32_t n) { for(unsigned i=0;i<4;++i) input[in_size++]=(uint8_t)(n>>(8*i)); }
static void reset_test(void) {
    memset(memory,0,sizeof memory); in_size=in_pos=out_size=ran=quiet_calls=jumps=0;
    pending=unsafe=corrupt_ram=memory_dma_busy=external_takeover=external_network_started=corrupt_after_done=0;external_state_untrusted=0; deny_quiet_from=1; ticks=0;
    network_success=network_corrupt=0;network_crc=0;
    image_valid=image_entry=image_length=image_network=0;legacy_crc=legacy_record_crc=0;legacy_pending=0;
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

}
static int run_loop(void) {
    int result=setjmp(escaped);
    if(!result) boot_loop();
    return result;
}
int main(void) {
    unsigned cases=0;
    reset_test(); session(1,0);
    assert(run_loop()==1 && ran==1 && jumps==1 && quiet_calls==2);
    assert(contains("VDON") && contains("DOWNLOAD OK") && contains("AUTOBOOT")); ++cases;
    reset_test(); assert(!network_download()); session(1,0);
    assert(run_loop()==1 && ran==1 && !image_network);
    assert(contains("UART recovery") && contains("VDON")); ++cases;
    reset_test(); assert(!network_download()); pending='d'; session(0,0);
    assert(run_loop()==1 && ran==1 && !pending); ++cases;
    reset_test(); unsafe=1; deny_quiet_from=2; session(1,0);
    assert(run_loop()==2 && !ran && !jumps && quiet_calls==2 && !image_valid);
    assert(contains("DMA BUSY; RESET REQUIRED"));
    unsafe=0; input[in_size++]='g';
    assert(run_loop()==2 && !ran && quiet_calls==2 && !image_valid);
    session(1,0);assert(run_loop()==1&&ran==1&&quiet_calls==4); ++cases;
    reset_test(); session(1,1);
    assert(run_loop()==2 && !ran && !image_valid && quiet_calls==1);
    assert(contains("IMAGE CRC FAIL") && !contains("VDON")); ++cases;
    reset_test(); corrupt_ram=1; session(1,0);
    assert(run_loop()==2 && !ran && !image_valid && quiet_calls==1);
    assert(contains("RAM CRC FAIL") && !contains("VDON")); ++cases;
    test_length=8193;
    const unsigned offsets[]={0,255,256,4095,4096,8192};
    for(unsigned epoch=0;epoch<2;++epoch) {
        reset_test(); session(1,0);
        assert(run_loop()==1 && ran==1 && jumps==1); ++cases;
        for(unsigned i=0;i<sizeof offsets/sizeof offsets[0];++i) {
            reset_test(); corrupt_ram=1; corrupt_offset=offsets[i]; session(1,0);
            assert(run_loop()==2 && !ran && !jumps && !image_valid);
            assert(contains("RAM CRC FAIL") && !contains("VDON")); ++cases;
        }
    }
    reset_test();unsafe=1;input[in_size++]='d';assert(run_loop()==2&&!image_valid&&!ran&&!contains("VLOAD1"));++cases;
    reset_test();memory_dma_busy=1;input[in_size++]='d';assert(run_loop()==2&&!image_valid&&!ran&&!contains("VLOAD1"));++cases;
    test_length=16;reset_test();corrupt_after_done=1;session(1,0);
    assert(run_loop()==2&&!image_valid&&!ran&&contains("DOWNLOAD OK")&&contains("RAM CRC FAIL")&&!contains("AUTOBOOT"));++cases;
    corrupt_after_done=0;session(1,0);assert(run_loop()==1&&ran==1&&!image_valid);++cases;
    test_length=16;reset_test();external_takeover=1;session(1,0);input[in_size++]='n';input[in_size++]='d';input[in_size++]='g';
    assert(run_loop()==2&&ran==1&&external_state_untrusted&&external_network_started&&!image_valid&&contains("EXTERNAL STATE LOCKED"));++cases;
    test_length=16;reset_test();network_success=1;
    int result=setjmp(escaped);if(!result)boot_main();
    assert(result==1&&ran==1&&jumps==1&&!image_valid&&contains("AUTOBOOT"));++cases;
    reset_test();network_success=network_corrupt=1;
    result=setjmp(escaped);if(!result)boot_main();
    assert(result==2&&!ran&&!jumps&&!image_valid&&contains("RAM CRC FAIL")&&!contains("AUTOBOOT"));++cases;
    printf("BOOTROM_UART_RECOVERY_PASS cases=%u netfail_uart_run=1 cancel_uart_run=1 verified_run=1 busy_blocks_run=1 stream_crc_negative=1 ram_crc_negative=1 rtl_proof=0\n",cases);
    return 0;
}
