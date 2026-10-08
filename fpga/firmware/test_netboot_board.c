/* Firmware MMIO ordering oracle. Does not simulate PHY, CDC or actual RTL. */
#define NETBOOT_BOARD_TEST 1
#define NETBOOT_POSTED_RX 1
#define CPU_HZ 1000ULL
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "netboot.h"
static int board_protocol(struct nb_ops *,const char *,uint32_t *,uint32_t *);
#define nb_tftp board_protocol
#include "netboot_board.c"
int firmware_ram_dma_idle(void){return 1;}
int firmware_ram_prepare(uint64_t *f,uint64_t *s){*f=1;*s=2;return 1;}
#undef nb_tftp

static uint8_t actual_ram[8192];
uint8_t *nb_test_ram(void) { return actual_ram; }
struct posted_descriptor {
    uintptr_t address;
    unsigned capacity, bytes, error, state; /* 0 free, 1 pending, 2 active, 3 complete */
};
static struct {
    struct posted_descriptor queue[16];
    uintptr_t queue_address;
    unsigned queue_capacity, queue_head, queue_tail, queue_count;
    unsigned posts, pops, queue_enables, queue_disables, queue_accesses, produced;
    unsigned queue_cap, mac_slots, frame_limit, write_tail, memory_delay, frame_bytes;
    int queue_enabled, queue_stopped, queue_active, frame_done, bad_completion_address;
    uint64_t tick, rx, tx, control, address, stop, mdio, mac_address;
    unsigned frames, delay, tail, writes, starts, dma_stops, controls;
    int stuck_producer, stuck_dma, old_mac, next_uart, bad_phy, verified, fail_after_verified;
    char log[65536]; unsigned logged;
} hw;
static int board_protocol(struct nb_ops *ops,const char *file,uint32_t *entry,uint32_t *length) {
    if(!hw.verified) return nb_tftp(ops,file,entry,length);
    unsigned window=NETBOOT_WINDOW;
    if(window>hw.queue_cap) window=hw.queue_cap;
    if(window>(hw.mac_slots?hw.mac_slots:1)) window=hw.mac_slots?hw.mac_slots:1;
    assert(ops->request_blksize==(posted_mode?NETBOOT_BLOCK_BYTES:0U));
    assert(ops->request_windowsize==(posted_mode?window:0U));
    *entry=RAM_BASE; *length=16;
    if(hw.fail_after_verified) hw.stuck_producer=1;
    return 1; /* separately tested protocol; this injects only its terminal result */
}
static void queue_complete(unsigned error) {
    assert(hw.queue_active>=0);
    struct posted_descriptor *d=&hw.queue[hw.queue_active];
    d->error|=error; d->state=3; hw.queue_active=-1; hw.frame_done=0;
}
static void queue_step(void) {
    if(hw.queue_active>=0) {
        struct posted_descriptor *d=&hw.queue[hw.queue_active];
        if(hw.frame_done) {
            if(!hw.stuck_dma && (!hw.memory_delay || !--hw.memory_delay)) queue_complete(0);
        } else if(hw.queue_stopped) {
            if(!hw.stuck_dma) queue_complete(1);
        } else if(hw.frames && !hw.delay && !hw.stuck_producer) {
            if(hw.tail) --hw.tail;
            else {
                d->bytes=hw.frame_bytes?hw.frame_bytes:64;
                d->error=d->bytes>d->capacity;
                unsigned n=d->error?d->capacity:d->bytes;
                memset((void *)d->address,(int)(0x31+hw.produced++),n);
                --hw.frames; hw.frame_done=1; hw.memory_delay=hw.write_tail;
                if(!hw.memory_delay && !hw.stuck_dma) queue_complete(0);
            }
        }
    }
    if(hw.queue_active<0) {
        for(unsigned n=0;n<hw.queue_count;++n) {
            unsigned slot=(hw.queue_head+n)%hw.queue_cap;
            if(hw.queue[slot].state!=1) continue;
            hw.queue[slot].state=2; hw.queue_active=(int)slot;
            if(hw.queue_stopped && !hw.stuck_dma) queue_complete(1);
            break;
        }
    }
}
static uint64_t queue_status(void) {
    unsigned pending=0, completed=0;
    for(unsigned i=0;i<hw.queue_cap;++i) {
        pending+=hw.queue[i].state==1; completed+=hw.queue[i].state==3;
    }
    assert(pending+completed+(hw.queue_active>=0)==hw.queue_count);
    return pending | (completed<<8) | ((uint64_t)(hw.queue_active>=0)<<16) |
        ((uint64_t)hw.queue_stopped<<17);
}
static void step(void) {
    ++hw.tick;
    if(hw.delay && !hw.stuck_producer) --hw.delay;
    if(hw.queue_enabled) { queue_step(); return; }
    if((hw.rx&1) && hw.frames && !hw.delay && !hw.stuck_producer) {
        if(hw.tail) --hw.tail;
        else { --hw.frames; hw.rx=2; }
    }
}
uint64_t nb_test_now(void) { step(); return hw.tick; }
uint64_t nb_test_read(uintptr_t base,unsigned offset) {
    step();
    if(base==DMA_BASE) {
        if(offset>=0xa0) { assert(hw.queue_cap>=1); ++hw.queue_accesses; }
        switch(offset) {
        case 0: return 0x56444d4100010001ULL;
        case 0x88: return hw.frame_limit;
        case 0x98: return 1 | (hw.queue_cap?2:0) | (hw.queue_cap<<8);
        case 0x48: return hw.queue_enabled?(hw.queue_active>=0):hw.rx;
        case VALENCE_NET_DMA_RX_QUEUE_CONTROL: return hw.queue_enabled;
        case VALENCE_NET_DMA_RX_QUEUE_STATUS: return queue_status();
        case VALENCE_NET_DMA_RX_COMPLETE_ADDRESS:
            assert(hw.queue[hw.queue_head].state==3);
            return hw.bad_completion_address?0:hw.queue[hw.queue_head].address;
        case VALENCE_NET_DMA_RX_COMPLETE_RESULT:
            assert(hw.queue[hw.queue_head].state==3);
            return hw.queue[hw.queue_head].bytes | ((uint64_t)hw.queue[hw.queue_head].error<<16);
        case 0x28: return hw.tx;
        case 0x50: return 64;
        default: return 0;
        }
    }
    assert(base==MAC_BASE);
    switch(offset) {
    case VGMAC_ID: return VALENCE_GMAC_ID;
    case VGMAC_CAP: return hw.old_mac?0:VGMAC_CAP_RX_STOP | (hw.mac_slots?((1ULL<<9) | ((uint64_t)hw.mac_slots<<24)):0);
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
            if(!value) {
                assert(hw.stop && !(hw.rx&1) && !(hw.tx&1));
                assert(!hw.queue_enabled && !hw.queue_count && hw.queue_active<0);
                ++hw.controls;
            }
            hw.control=value;
        } else if(offset==VGMAC_MDIO_COMMAND) hw.mdio=value;
        else if(offset==VGMAC_MAC_ADDRESS) hw.mac_address=value;
        return;
    }
    assert(base==DMA_BASE);
    if(offset>=0xa0) { assert(hw.queue_cap>=1); ++hw.queue_accesses; }
    if(offset==VALENCE_NET_DMA_RX_QUEUE_CONTROL) {
        assert(value<=1 && !hw.queue_count && hw.queue_active<0 && !(hw.rx&1));
        hw.queue_enabled=(int)value; hw.queue_stopped=0;
        if(value) ++hw.queue_enables; else ++hw.queue_disables;
    } else if(offset==VALENCE_NET_DMA_RX_POST_ADDRESS) hw.queue_address=value;
    else if(offset==VALENCE_NET_DMA_RX_POST_CAPACITY) hw.queue_capacity=(unsigned)value;
    else if(offset==VALENCE_NET_DMA_RX_POST) {
        assert(value==1 && hw.queue_enabled && !hw.queue_stopped && hw.queue_count<hw.queue_cap);
        assert(!(hw.queue_address&63) && hw.queue_capacity==POSTED_RX_BYTES);
        for(unsigned i=0;i<hw.queue_cap;++i)
            assert(!hw.queue[i].state || hw.queue[i].address!=hw.queue_address);
        assert(!hw.queue[hw.queue_tail].state);
        hw.queue[hw.queue_tail]=(struct posted_descriptor){hw.queue_address,hw.queue_capacity,0,0,1};
        hw.queue_tail=(hw.queue_tail+1)%hw.queue_cap; ++hw.queue_count; ++hw.posts;
    } else if(offset==VALENCE_NET_DMA_RX_COMPLETE_POP) {
        assert(value==1 && hw.queue_count && hw.queue[hw.queue_head].state==3);
        /* Releasing ownership may immediately destroy the old contents. The
         * firmware must finish all borrowed-byte consumption before this write. */
        memset((void *)hw.queue[hw.queue_head].address,0xa5,hw.queue[hw.queue_head].capacity);
        hw.queue[hw.queue_head].state=0; hw.queue_head=(hw.queue_head+1)%hw.queue_cap;
        --hw.queue_count; ++hw.pops;
    }
    if(offset==0x30 || offset==0x38 || offset==0x40) assert(!hw.queue_enabled && !(hw.rx&1));
    if(offset==0x30) { assert(value==(uintptr_t)rx_frame); hw.address=value; }
    if(offset==0x40) {
        assert(hw.address==(uintptr_t)rx_frame || !(value&1));
        if(value&1) { hw.rx=1; ++hw.starts; } else hw.rx=0;
    }
    if(offset==0x90) {
        assert(hw.stop && !hw.frames && !hw.delay && !hw.stuck_producer);
        ++hw.dma_stops;
        if(hw.queue_enabled) hw.queue_stopped=1;
        else if(!hw.stuck_dma) hw.rx=6;
    }
    if(offset==0x20) hw.tx=(value&1)?2:0;
}
int nb_test_uart_get(void) { int c=hw.next_uart; hw.next_uart=-1; return c; }
void nb_test_uart_put(uint8_t c) {
    assert(hw.logged+1<sizeof hw.log); hw.log[hw.logged++]=(char)c; hw.log[hw.logged]=0;
}
static void reset_hw(void) {
    memset(&hw,0,sizeof hw); hw.next_uart=-1; hw.queue_active=-1; hw.mac_slots=4; hw.frame_limit=2048;
    posted_available=posted_mode=posted_used=0; posted_owned=0;
    posted_frames=posted_drops=0; posted_copy_ticks=0; borrowed_valid=0;
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
static void posted_begin(void) {
    reset_hw(); active=1; hw.control=11; hw.queue_cap=4;
    assert(start_posted_rx() && posted_mode && posted_owned==15);
    assert(hw.posts==4 && hw.queue_count==4);
}
static void posted_quiet_case(unsigned frames,unsigned media_delay,unsigned status_tail,unsigned write_tail) {
    posted_begin();
    hw.frames=frames; hw.delay=media_delay; hw.tail=status_tail; hw.write_tail=write_tail;
    assert(board_netboot_quiet());
    assert(!active && !armed && !posted_mode && !posted_owned && !hw.control);
    assert(!hw.queue_enabled && !hw.queue_count && hw.queue_active<0);
    assert(hw.stop && hw.controls==1 && hw.queue_disables==1 && hw.posts==hw.pops);
    assert(hw.produced==frames);
    unsigned writes=hw.writes;
    assert(board_netboot_quiet() && hw.writes==writes);
}
static unsigned posted_cases(void) {
    unsigned cases=0;
    uint32_t entry=0,length=0;
    reset_hw(); hw.queue_cap=4; hw.verified=1;
    assert(board_netboot(&entry,&length) && entry==RAM_BASE && length==16);
    assert(hw.queue_enables==1 && hw.queue_disables==1 && hw.posts==4 && hw.pops==4);
    assert(!posted_mode && !posted_owned && !active); ++cases;
    /* A queue-aware binary must make no additive queue access on old/shallow RTL. */
    for(unsigned depth=0;depth<4;++depth) {
        reset_hw(); hw.queue_cap=depth; hw.verified=1;
        assert(board_netboot(&entry,&length));
        if(depth==1 || depth==2) assert(hw.posts==depth && hw.pops==depth && hw.queue_accesses);
        else assert(!hw.queue_accesses && !hw.posts);
        ++cases;
    }
    posted_begin();
    assert(recv(0,10)==0 && posted_owned==15 && hw.queue_count==4);
    assert(hw.posts==4 && !hw.pops && !hw.dma_stops);
    assert(board_netboot_quiet()); ++cases;
    /* All four frames can complete without any CPU completion handling. */
    posted_begin(); hw.frames=4; hw.frame_bytes=1110;
    for(unsigned i=0;i<16;++i) step();
    assert(hw.frames==0 && ((queue_status()>>8)&255)==4 && hw.posts==4 && !hw.pops);
    for(unsigned frame=0;frame<4;++frame) {
        assert(recv(0,10)==1110);
        uint8_t *payload=received_frame(0);
#ifdef NB_TEST_EARLY_RELEASE
        assert(release_borrowed_rx(1)); /* independent negative: POP poisons bytes */
#endif
        for(unsigned i=0;i<1110;++i) assert(payload[i]==0x31+frame);
        for(unsigned i=0;i<8;++i) step();
        assert(borrowed_valid && payload==received_frame(0));
        for(unsigned i=0;i<1110;++i) assert(payload[i]==0x31+frame);
        assert(hw.posts==4+frame && hw.pops==frame && posted_owned==15 && !posted_copy_ticks);
    }
    assert(board_netboot_quiet()); ++cases;
    /* Oversize/error completions are drained and recycled without publishing data. */
    posted_begin(); hw.frames=1; hw.frame_bytes=POSTED_RX_BYTES+1;
    assert(recv(0,40)==0 && hw.posts==5 && hw.pops==1);
    assert(!borrowed_valid);
    hw.frames=1; hw.frame_bytes=1070;
    assert(recv(0,40)==1070 && received_frame(0)[0]==0x32);
    assert(board_netboot_quiet()); ++cases;
    /* UART cancellation cannot reclaim anything until the producer barrier. */
    posted_begin(); hw.next_uart='d';
    assert(recv(0,10)==-1 && !hw.pops && !hw.dma_stops && posted_owned==15);
    assert(board_netboot_quiet() && !posted_mode && !posted_owned);
    assert(board_netboot_command()=='d' && !board_netboot_command()); ++cases;
    posted_quiet_case(0,0,0,0); ++cases;
    posted_quiet_case(10,0,0,0); ++cases;
    posted_quiet_case(3,45,0,0); ++cases;
    posted_quiet_case(2,0,50,0); ++cases;
    posted_quiet_case(4,0,0,20); ++cases;
    posted_begin(); hw.frames=1; hw.stuck_producer=1;
    assert(!board_netboot_quiet() && active && posted_mode && posted_owned==15);
    assert(!hw.dma_stops && !hw.controls && strstr(hw.log,"producer_drain_timeout"));
    hw.stuck_producer=0; assert(board_netboot_quiet() && !active); ++cases;
    posted_begin(); hw.stuck_dma=1;
    assert(!board_netboot_quiet() && active && posted_mode && hw.queue_count==4);
    assert(hw.queue_stopped && !hw.controls && strstr(hw.log,"rx_dma_stop_timeout"));
    hw.stuck_dma=0; assert(board_netboot_quiet() && !active && !posted_mode); ++cases;
    /* A live DDR tail survives the MAC producer barrier and cannot be bypassed. */
    posted_begin(); hw.frames=1; hw.stuck_dma=1;
    for(unsigned i=0;i<hw.queue_cap;++i) step();
    assert(!hw.frames && hw.frame_done);
    assert(!board_netboot_quiet() && hw.queue_enabled && hw.queue_count==4 && !hw.controls);
    hw.stuck_dma=0; assert(board_netboot_quiet() && !hw.queue_count); ++cases;
    reset_hw(); hw.queue_cap=4; hw.next_uart='d';
    assert(!board_netboot(&entry,&length) && !active && !posted_mode);
    assert(board_netboot_command()=='d' && !board_netboot_command()); ++cases;
    reset_hw(); hw.queue_cap=4;
    assert(!board_netboot(&entry,&length) && !active && !posted_mode);
    assert(stats.failure==NB_RETRY_LIMIT && hw.posts==hw.pops); ++cases;
    reset_hw(); hw.queue_cap=4; hw.verified=1; hw.fail_after_verified=1;
    entry=123; length=456;
    assert(!board_netboot(&entry,&length) && active && posted_mode);
    assert(entry==123 && length==456);
    hw.stuck_producer=0; assert(board_netboot_quiet()); ++cases;
    posted_begin(); hw.frames=1; hw.bad_completion_address=1;
    assert(recv(0,40)==-1 && hw.pops==1 && hw.posts==4);
    assert(!borrowed_valid);
    hw.bad_completion_address=0; assert(board_netboot_quiet()); ++cases;
    posted_begin(); hw.bad_completion_address=1;
    assert(!board_netboot_quiet() && !posted_mode && !hw.queue_enabled && !hw.queue_count);
    assert(active && !hw.controls); /* owner corruption must never publish boot success */
    hw.bad_completion_address=0; assert(board_netboot_quiet()); ++cases;
    return cases;
}
static unsigned store_cases(void) {
    uint8_t from[96]; unsigned cases=0;
    for(unsigned i=0;i<sizeof from;++i) from[i]=(uint8_t)(3*i+17);
    for(unsigned src=0;src<8;++src)
        for(unsigned dst=0;dst<8;++dst)
            for(unsigned n=0;n<=64;++n) {
                memset(actual_ram,0xa5,sizeof actual_ram);
                assert(store(0,16+dst,from+src,n)==0);
                assert(!memcmp(actual_ram+16+dst,from+src,n));
                for(unsigned i=0;i<16+dst;++i) assert(actual_ram[i]==0xa5);
                for(unsigned i=16+dst+n;i<sizeof actual_ram;++i) assert(actual_ram[i]==0xa5);
                ++cases;
            }
    memset(actual_ram,0xa5,sizeof actual_ram);
    assert(store(0,(uint32_t)IMAGE_LIMIT+1,from,0)==-1);
    assert(store(0,(uint32_t)IMAGE_LIMIT-1,from,2)==-1);
    for(unsigned i=0;i<sizeof actual_ram;++i) assert(actual_ram[i]==0xa5);
    return cases+2;
}
static void prepare_cases(void) {
    posted_begin();hw.frames=4;hw.frame_bytes=1110;
    for(unsigned i=0;i<16;i++)step();
    assert(recv(0,10)==1110 && borrowed_valid);
    hw.frames=1;
    assert(prepare_verify(0)==0 && !active && !posted_mode && !posted_owned && !borrowed_valid);
    assert(send(0,60)==-1); /* CRC failure cannot restart TX after quiet. */
    puts("BOOTROM_RAM_PREPARE_BOARD_PASS cases=1 borrowed_then_backlog=1 no_tx_after_quiet=1");
}
int main(void) {
    prepare_cases();
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
    unsigned queued=posted_cases();
    unsigned stores=store_cases();
    printf("BOOTROM_STORE_ALIGN_PASS cases=%u source_alignments=8 destination_alignments=8 lengths=0..64 canaries=1\n",stores);
    printf("BOOTROM_POSTED_RX_ORDER_PASS cases=%u burst4=1 borrowed_until_next_receive=1 consumption_before_pop=1 oversized=1 legacy_fallback=1 producer_barrier=1 ddr_tail=1 cancel=1 rtl_proof=0\n",queued);
    printf("BOOTROM_MMIO_ORDER_PASS cases=%u backlog=1 half_frame=1 status_tail=1 timeout_recovery=1 cancel=1 old_capability=1 netfail_uart_preflight=1 rtl_proof=0\n",cases);
    return 0;
}
