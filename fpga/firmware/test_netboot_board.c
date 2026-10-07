/* Firmware MMIO ordering oracle. Does not simulate PHY, CDC or actual RTL. */
#define NETBOOT_BOARD_TEST 1
#define CPU_HZ 1000ULL
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "netboot.h"
static int board_protocol(struct nb_ops *,const char *,uint32_t *,uint32_t *);
#define nb_tftp board_protocol
#include "netboot_board.c"
#undef nb_tftp

static uint8_t actual_ram[8192];
uint8_t *nb_test_ram(void) { return actual_ram; }
static struct {
    uint64_t tick, rx, tx, control, address, stop, mdio, mac_address;
    unsigned frames, delay, tail, writes, starts, dma_stops, controls;
    int stuck_producer, stuck_dma, old_mac, next_uart, bad_phy, verified, fail_after_verified;
    char log[65536]; unsigned logged;
} hw;
static int board_protocol(struct nb_ops *ops,const char *file,uint32_t *entry,uint32_t *length) {
    if(!hw.verified) return nb_tftp(ops,file,entry,length);
    *entry=RAM_BASE; *length=16;
    if(hw.fail_after_verified) hw.stuck_producer=1;
    return 1; /* separately tested protocol; this injects only its terminal result */
}
static void step(void) {
    ++hw.tick;
    if(hw.delay && !hw.stuck_producer) --hw.delay;
    if((hw.rx&1) && hw.frames && !hw.delay && !hw.stuck_producer) {
        if(hw.tail) --hw.tail;
        else { --hw.frames; hw.rx=2; }
    }
}
uint64_t nb_test_now(void) { step(); return hw.tick; }
uint64_t nb_test_read(uintptr_t base,unsigned offset) {
    step();
    if(base==DMA_BASE) {
        switch(offset) {
        case 0: return 0x56444d4100010001ULL;
        case 0x98: return 1;
        case 0x48: return hw.rx;
        case 0x28: return hw.tx;
        case 0x50: return 64;
        default: return 0;
        }
    }
    assert(base==MAC_BASE);
    switch(offset) {
    case VGMAC_ID: return VALENCE_GMAC_ID;
    case VGMAC_CAP: return hw.old_mac?0:VGMAC_CAP_RX_STOP;
    case VGMAC_RX_STOP:
        assert(!hw.old_mac);
        return hw.stop | ((hw.stop && !hw.frames && !hw.delay && !hw.stuck_producer)?2:0);
    case VGMAC_STATUS: return (hw.frames || hw.delay || hw.stuck_producer)?4:0;
    case VGMAC_CONTROL: return hw.control;
    case VGMAC_MAC_ADDRESS: return hw.mac_address;
    case VGMAC_MDIO_STATUS: return 2;
    case VGMAC_MDIO_RESULT: {
        if(hw.bad_phy) return 1UL<<16;
        unsigned reg=(unsigned)(hw.mdio>>23)&31;
        switch(reg) {
        case 2: return 0x1c; case 3: return 0xc910; case 0x15: return 8;
        case 1: return 0x24; case 0x1a: return 0x28; default: return 0;
        }
    }
    default: return 0;
    }
}
void nb_test_write(uintptr_t base,unsigned offset,uint64_t value) {
    step(); ++hw.writes;
    if(base==MAC_BASE) {
        assert(!hw.old_mac);
        if(offset==VGMAC_RX_STOP) { assert(value<=1); hw.stop=value; }
        else if(offset==VGMAC_CONTROL) {
            assert(!hw.frames && !hw.delay && !hw.stuck_producer);
            if(!value) { assert(hw.stop && !(hw.rx&1) && !(hw.tx&1)); ++hw.controls; }
            hw.control=value;
        } else if(offset==VGMAC_MDIO_COMMAND) hw.mdio=value;
        else if(offset==VGMAC_MAC_ADDRESS) hw.mac_address=value;
        return;
    }
    assert(base==DMA_BASE);
    if(offset==0x30 || offset==0x38 || offset==0x40) assert(!(hw.rx&1));
    if(offset==0x30) { assert(value==(uintptr_t)rx_frame); hw.address=value; }
    if(offset==0x40) {
        assert(hw.address==(uintptr_t)rx_frame || !(value&1));
        if(value&1) { hw.rx=1; ++hw.starts; } else hw.rx=0;
    }
    if(offset==0x90) {
        assert(hw.stop && !hw.frames && !hw.delay && !hw.stuck_producer);
        ++hw.dma_stops;
        if(!hw.stuck_dma) hw.rx=6;
    }
    if(offset==0x20) hw.tx=(value&1)?2:0;
}
int nb_test_uart_get(void) { int c=hw.next_uart; hw.next_uart=-1; return c; }
void nb_test_uart_put(uint8_t c) {
    assert(hw.logged+1<sizeof hw.log); hw.log[hw.logged++]=(char)c; hw.log[hw.logged]=0;
}
static void reset_hw(void) {
    memset(&hw,0,sizeof hw); hw.next_uart=-1;
    active=armed=pending_command=0; stats=(struct nb_stats){0};
    drained_frames=0; current_stage=NB_INIT; failure_reported=0; ram_crc_valid=0;
}
static void quiet_case(unsigned frames,unsigned media_delay,unsigned status_tail) {
    reset_hw(); active=1; hw.control=11;
    hw.frames=frames; hw.delay=media_delay; hw.tail=status_tail;
    assert(board_netboot_quiet());
    assert(!active && !armed && !(hw.rx&1) && !hw.control);
    assert(hw.stop==1 && hw.controls==1);
    assert(hw.starts>=frames);
    unsigned writes=hw.writes;
    assert(board_netboot_quiet() && writes==hw.writes); /* repeated UART RUN preflight */
}
int main(void) {
    unsigned cases=0;
    quiet_case(0,0,0); ++cases;
    quiet_case(4,0,0); ++cases; /* backlog: descriptors must be re-armed */
    quiet_case(2,45,0); ++cases; /* admitted media half-frame is still producing */
    quiet_case(1,0,50); ++cases; /* frame body done but six-word status tail pending */
    reset_hw(); active=1; hw.frames=1; hw.stuck_producer=1;
    assert(!board_netboot_quiet() && active && armed && (hw.rx&1));
    assert(!hw.dma_stops && !hw.controls);
    assert(strstr(hw.log,"producer_drain_timeout"));
    hw.stuck_producer=0;
    assert(board_netboot_quiet() && !active && !armed); ++cases;
    reset_hw(); active=1; armed=1; hw.rx=1; hw.stuck_dma=1;
    assert(!board_netboot_quiet() && active && armed && !hw.controls);
    assert(strstr(hw.log,"rx_dma_stop_timeout"));
    hw.stuck_dma=0; assert(board_netboot_quiet()); ++cases;
    reset_hw(); active=1;
    assert(recv(0,10)==0 && armed && (hw.rx&1) && !hw.dma_stops);
    unsigned starts=hw.starts; hw.frames=1;
    assert(recv(0,10)==64 && !armed && hw.starts==starts);
    assert(board_netboot_quiet()); ++cases;
    reset_hw(); active=1; hw.next_uart='d';
    assert(recv(0,10)==-1 && armed && !hw.dma_stops);
    assert(board_netboot_quiet() && !active && !armed);
    assert(board_netboot_command()=='d' && !board_netboot_command()); ++cases;
    reset_hw(); hw.old_mac=1; uint32_t entry=123,length=456;
    assert(!board_netboot(&entry,&length));
    assert(!active && !armed && !hw.writes && entry==123 && length==456);
    assert(board_netboot_quiet()); ++cases;
    reset_hw(); hw.bad_phy=1;
    assert(!board_netboot(&entry,&length) && !active && !armed);
    assert(board_netboot_quiet()); ++cases;
    reset_hw(); hw.next_uart='d';
    assert(!board_netboot(&entry,&length) && !active && !armed);
    assert(board_netboot_command()=='d' && !board_netboot_command()); ++cases;
    reset_hw();
    assert(!board_netboot(&entry,&length) && !active && !armed); /* no ARP peer */
    assert(stats.failure==NB_RETRY_LIMIT && !board_netboot_command());
    assert(board_netboot_quiet()); ++cases;
    reset_hw(); hw.verified=1; pending_command='d';
    assert(board_netboot(&entry,&length) && !active && !armed && !pending_command);
    assert(entry==RAM_BASE && length==16 && board_netboot_quiet()); ++cases;
    reset_hw(); hw.verified=1; hw.fail_after_verified=1; entry=123; length=456;
    assert(!board_netboot(&entry,&length) && active && armed);
    assert(entry==123 && length==456); /* verification alone cannot publish success */
    hw.stuck_producer=0; assert(board_netboot_quiet() && !active && !armed); ++cases;
    reset_hw(); hw.next_uart='d';
    assert(verify(0,sizeof actual_ram,0)==-2 && !ram_crc_valid);
    assert(board_netboot_command()=='d' && !board_netboot_command()); ++cases;
    reset_hw();
    assert(verify(0,sizeof actual_ram,nb_crc_update(~0U,actual_ram,sizeof actual_ram)^~0U)==0);
    assert(ram_crc_valid); ++cases;
    /* Independent pre-stream oracle; mutate after storing, before real verify. */
    uint32_t wanted=~0U;
    for(unsigned i=0;i<sizeof actual_ram;++i) {
        actual_ram[i]=(uint8_t)(i*17+3); wanted^=actual_ram[i];
        for(unsigned b=0;b<8;++b) wanted=(wanted>>1)^(0xedb88320U&(0U-(wanted&1)));
    }
    wanted=~wanted;
    const unsigned offsets[]={0,255,256,4095,4096,sizeof actual_ram-1};
    for(unsigned epoch=0;epoch<2;++epoch) {
        reset_hw(); assert(verify(0,sizeof actual_ram,wanted)==0); ++cases;
        for(unsigned i=0;i<sizeof offsets/sizeof offsets[0];++i) {
            reset_hw(); actual_ram[offsets[i]]^=1;
            assert(verify(0,sizeof actual_ram,wanted)==-1 && ram_crc_valid && ram_crc!=wanted);
            actual_ram[offsets[i]]^=1; ++cases;
        }
    }
    printf("BOOTROM_MMIO_ORDER_PASS cases=%u backlog=1 half_frame=1 status_tail=1 timeout_recovery=1 cancel=1 old_capability=1 netfail_uart_preflight=1 rtl_proof=0\n",cases);
    return 0;
}
