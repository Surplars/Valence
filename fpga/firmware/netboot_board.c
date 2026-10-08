#include "netboot.h"
#include "valence_gmac.h"
#include "ethernet_dma.h"
#ifndef NETBOOT_POSTED_RX
#define NETBOOT_POSTED_RX 0
#endif
#ifndef NETBOOT_BLOCK_BYTES
#define NETBOOT_BLOCK_BYTES 1024U
#endif
#ifndef NETBOOT_WINDOW
#define NETBOOT_WINDOW 4U
#endif
#ifndef NETBOOT_RX_SLOTS
#define NETBOOT_RX_SLOTS 4U
#endif
#ifndef CPU_HZ
#define CPU_HZ 100000000ULL
#endif
#ifndef BOARD_RAM_BYTES
#define BOARD_RAM_BYTES (512UL*1024*1024)
#endif
#ifndef NETBOOT_IP
#define NETBOOT_IP 0xc0a8891eU /* 192.168.137.30 */
#endif
#ifndef NETBOOT_SERVER
#define NETBOOT_SERVER 0xc0a88901U /* 192.168.137.1, same Ethernet segment */
#endif
#ifndef NETBOOT_FILE
#define NETBOOT_FILE "valence.vld"
#endif
#include "board_memory.h"
#include "ram_verify.h"
#define DMA_BASE 0x10002000UL
#define MAC_BASE 0x10040000UL
#define UART ((volatile uint8_t *)0x10000000UL)
/* These lie in the monitor's reserved 16 KiB, excluded by IMAGE_LIMIT and DT. */
/* TX contains only ARP, ACK, bounded RRQ and error packets, all below 512.
 * Four 1152-byte posted slots cover a 1024-byte block plus even a 60-byte IPv4
 * header (1110 bytes total). Keep the 8 KiB stack; legacy and posted receive storage share an exclusive union. */
static uint8_t tx_frame[512] __attribute__((aligned(64)));
#if NETBOOT_POSTED_RX
#define POSTED_RX_COUNT NETBOOT_RX_SLOTS
/* Ethernet + maximum IPv4 header + UDP + TFTP =86 bytes; align each slot. */
#define POSTED_RX_BYTES ((NETBOOT_BLOCK_BYTES + 86U + 63U) & ~63U)
_Static_assert(NETBOOT_BLOCK_BYTES == 512 || NETBOOT_BLOCK_BYTES == 1024, "supported TFTP block sizes");
_Static_assert(POSTED_RX_COUNT >= 1 && POSTED_RX_COUNT <= 16, "posted software slots 1..16");
_Static_assert(NETBOOT_WINDOW >= 1 && NETBOOT_WINDOW <= POSTED_RX_COUNT &&
               NETBOOT_WINDOW <= NB_TFTP_WINDOW_MAX, "window must fit the posted pool");
_Static_assert(POSTED_RX_COUNT * POSTED_RX_BYTES <= 4608, "posted pool exceeds reserved boot scratch budget");
/* Modes are mutually exclusive. Borrowed posted frames remove the duplicate
 * receive-copy buffer while preserving a full legacy 2048-byte DMA buffer. */
static union {
    uint8_t legacy[2048];
    uint8_t posted[POSTED_RX_COUNT][POSTED_RX_BYTES];
} rx_storage __attribute__((aligned(64)));
#define rx_frame rx_storage.legacy
#define posted_rx rx_storage.posted
static unsigned borrowed_slot;
static int borrowed_valid;
static unsigned posted_count, negotiated_window_cap;
static unsigned posted_owned;
static int posted_available, posted_mode, posted_used;
static unsigned posted_frames, posted_drops;
static uint64_t posted_copy_ticks;
#else
static uint8_t rx_frame[2048] __attribute__((aligned(64)));
#endif
static int active, armed, pending_command, hardware_probed;
static struct nb_stats stats;
static enum nb_stage current_stage;
static uint64_t stage_start, init_ticks, drain_ticks, mac_stop_ticks, transfer_ticks;
static uint64_t ram_flush_ticks,ram_sweep_ticks,ram_readback_ticks;
static uint32_t ram_crc;
static unsigned drained_frames;
static int ram_crc_valid, failure_reported;
static const char *const stages[]={"init","arp","rx","header","stream_crc",
    "ram_crc","rx_tx_drain","mac_stop","jump","ram_prepare"};
#ifdef NETBOOT_BOARD_TEST
/* A scripted MMIO oracle tests firmware ordering, NOT physical CDC behavior. */
extern uint64_t nb_test_now(void);
extern uint64_t nb_test_read(uintptr_t,unsigned);
extern void nb_test_write(uintptr_t,unsigned,uint64_t);
extern int nb_test_uart_get(void);
extern void nb_test_uart_put(uint8_t);
extern uint8_t *nb_test_ram(void);
static uint64_t now(void *unused) { (void)unused; return nb_test_now(); }
static void fence(void) {}
static uint64_t read64(uintptr_t base,unsigned offset) { return nb_test_read(base,offset); }
static void write64(uintptr_t base,unsigned offset,uint64_t value) { nb_test_write(base,offset,value); }
static int uart_get(void) { return nb_test_uart_get(); }
static void uart_put(uint8_t c) { nb_test_uart_put(c); }
#else
/* GCC may lower aggregate initialization to memcpy even with -ffreestanding. */
void *memcpy(void *to,const void *from,size_t n) {
    uint8_t *d=to; const uint8_t *s=from;
    for(size_t i=0;i<n;++i) d[i]=s[i];
    return to;
}
void *memset(void *to,int value,size_t n) {
    uint8_t *d=to; for(size_t i=0;i<n;++i) d[i]=(uint8_t)value; return to;
}
static uint64_t now(void *unused) {
    /* BoardSocTop.timerTick=true; MachineTimer.timeValue feeds the TIME CSR.
     * This is CPU_HZ ticks/second on this fixed-clock board, not retired cycles. */
    (void)unused; uint64_t value; __asm__ volatile("rdtime %0":"=r"(value) :: "memory"); return value;
}
static void fence(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static uint64_t read64(uintptr_t base,unsigned offset) {
    uint64_t value=*(volatile uint64_t *)(base+offset); fence(); return value;
}
static void write64(uintptr_t base,unsigned offset,uint64_t value) {
    fence(); *(volatile uint64_t *)(base+offset)=value; fence();
}
static int uart_get(void) { return UART[5]&1?UART[0]:-1; }
static void uart_put(uint8_t c) { while(!(UART[5]&0x20)) {} UART[0]=c; }
#endif
static uint8_t *ram_pointer(uint32_t offset) {
#ifdef NETBOOT_BOARD_TEST
    return nb_test_ram()+offset;
#else
    return (uint8_t *)(RAM_BASE+offset);
#endif
}
static void text(const char *s) { while(*s) uart_put((uint8_t)*s++); }
static void number(uint64_t n) {
    char b[21]; unsigned i=0;
    do { b[i++]=(char)('0'+n%10); n/=10; } while(n);
    while(i) uart_put((uint8_t)b[--i]);
}
static void field(const char *name,uint64_t value) { text(" "); text(name); text("="); number(value); }
static void hexfield(const char *name,uint64_t value) {
    text(" "); text(name); text("=0x");
    for(int shift=60;shift>=0;shift-=4) {
        unsigned d=(unsigned)(value>>shift)&15; uart_put((uint8_t)(d<10?'0'+d:'a'+d-10));
    }
}
static void begin(enum nb_stage value) {
    current_stage=value; stage_start=now(0);
    text("NB stage="); text(stages[value]); text(" begin\r\n");
}
static void ended(uint64_t ticks) {
    text("NB stage="); text(stages[current_stage]); text(" ok"); field("ticks",ticks); text("\r\n");
}
static int failed(const char *reason) {
    failure_reported=1;
    uint64_t elapsed=now(0)-stage_start;
    uint64_t rx=0,tx=0,bytes=0,mac=0,control=0,stopped=0;
    if(active) {
        rx=read64(DMA_BASE,0x48); tx=read64(DMA_BASE,0x28); bytes=read64(DMA_BASE,0x50);
        mac=read64(MAC_BASE,VGMAC_STATUS); control=read64(MAC_BASE,VGMAC_CONTROL);
        stopped=read64(MAC_BASE,VGMAC_RX_STOP);
    }
    text("NB fail stage="); text(stages[current_stage]); text(" reason="); text(reason);
    field("ticks",elapsed);
    field("received",stats.received); field("expected_length",stats.expected_length);
    if(current_stage==NB_HEADER) {
        hexfield("expected_header_crc",stats.header_crc_expected);
        hexfield("actual_header_crc",stats.header_crc_actual);
    }
    if(current_stage==NB_STREAM_CRC || current_stage==NB_RAM_CRC) {
        hexfield("expected_crc",stats.expected_crc); hexfield("stream_crc",stats.stream_crc);
        if(ram_crc_valid) hexfield("ram_crc",ram_crc);
    }
    if(active) {
        hexfield("rx_dma",rx); hexfield("tx_dma",tx); hexfield("rx_bytes",bytes);
        hexfield("mac",mac); hexfield("control",control); hexfield("rx_stop",stopped);
#if NETBOOT_POSTED_RX
        if(posted_mode) hexfield("rx_queue",read64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_STATUS));
#endif
    }
    text("\r\n"); return 0;
}
static int wait_bits(uintptr_t base,unsigned off,uint64_t mask,uint64_t value,uint64_t budget) {
    uint64_t start=now(0);
    do { if((read64(base,off)&mask)==value) return 1; } while(now(0)-start<budget);
    return 0;
}
static int abort_uart(void) {
    if(uart_get()=='d') { pending_command='d'; return 1; }
    return 0;
}
int board_netboot_command(void) {
    int c=pending_command; pending_command=0; return c;
}
static void arm_rx(void) {
    /* Only call after BUSY=0: descriptor ownership follows hardware, not armed. */
    write64(DMA_BASE,0x30,(uintptr_t)rx_frame); write64(DMA_BASE,0x38,sizeof rx_frame);
    write64(DMA_BASE,0x40,3); armed=1;
}
#if NETBOOT_POSTED_RX
static unsigned queue_owned(uint64_t status) {
    return (unsigned)(status&255)+((unsigned)(status>>8)&255)+((status>>16)&1);
}
static void post_rx(unsigned slot) {
    write64(DMA_BASE,VALENCE_NET_DMA_RX_POST_ADDRESS,(uintptr_t)posted_rx[slot]);
    write64(DMA_BASE,VALENCE_NET_DMA_RX_POST_CAPACITY,POSTED_RX_BYTES);
    write64(DMA_BASE,VALENCE_NET_DMA_RX_POST,1);
    posted_owned|=1U<<slot;
}
static int start_posted_rx(void) {
    unsigned hardware_slots=(unsigned)(read64(DMA_BASE,VALENCE_NET_DMA_CAPABILITIES)>>8)&255;
    uint64_t mac_cap=read64(MAC_BASE,VGMAC_CAP);
    unsigned mac_slots=(mac_cap&(1ULL<<9))?(unsigned)(mac_cap>>24)&255:1;
    if(!hardware_slots || hardware_slots>16 || (hardware_slots&(hardware_slots-1)) ||
       !mac_slots || mac_slots>16 || (mac_slots&(mac_slots-1))) return 0;
    posted_count=hardware_slots<POSTED_RX_COUNT?hardware_slots:POSTED_RX_COUNT;
    negotiated_window_cap=NETBOOT_WINDOW;
    if(negotiated_window_cap>posted_count) negotiated_window_cap=posted_count;
    if(negotiated_window_cap>mac_slots) negotiated_window_cap=mac_slots;
    write64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_CONTROL,1);
    if(!(read64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_CONTROL)&1)) return 0;
    posted_mode=1; posted_used=1; posted_owned=0; borrowed_valid=0;
    for(unsigned slot=0;slot<posted_count;++slot) post_rx(slot);
    return queue_owned(read64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_STATUS))==posted_count;
}
/* The returned frame stays DMA-owned and immutable until the next recv or
 * shutdown. Only after parsing/CRC/store may POP allow hardware to reuse it. */
static int release_borrowed_rx(int repost) {
    if(!borrowed_valid) return 1;
    if(borrowed_slot>=posted_count || !(posted_owned&(1U<<borrowed_slot)) ||
       read64(DMA_BASE,VALENCE_NET_DMA_RX_COMPLETE_ADDRESS)!=(uintptr_t)posted_rx[borrowed_slot]) return 0;
    unsigned slot=borrowed_slot;
    write64(DMA_BASE,VALENCE_NET_DMA_RX_COMPLETE_POP,1);
    posted_owned&=~(1U<<slot); borrowed_valid=0;
    if(repost) post_rx(slot);
    return 1;
}
static int complete_posted_rx(int copy_frame,int repost) {
    uint64_t address=read64(DMA_BASE,VALENCE_NET_DMA_RX_COMPLETE_ADDRESS);
    uint64_t result=read64(DMA_BASE,VALENCE_NET_DMA_RX_COMPLETE_RESULT);
    unsigned slot=POSTED_RX_COUNT, bytes=(unsigned)result&65535;
    for(unsigned i=0;i<POSTED_RX_COUNT;++i)
        if(address==(uintptr_t)posted_rx[i] && (posted_owned&(1U<<i))) slot=i;
    int good=slot<POSTED_RX_COUNT && !(result&VALENCE_NET_DMA_RX_COMPLETE_ERROR) &&
        bytes>0 && bytes<=POSTED_RX_BYTES;
    if(copy_frame) {
        if(good) {
            if(borrowed_valid) return -1;
            borrowed_slot=slot; borrowed_valid=1; ++posted_frames;
            return (int)bytes;
        } else ++posted_drops;
    }
    write64(DMA_BASE,VALENCE_NET_DMA_RX_COMPLETE_POP,1);
    if(slot==POSTED_RX_COUNT) return -1; /* never dereference an unowned address */
    posted_owned&=~(1U<<slot);
    if(repost) post_rx(slot);
    return good?(int)bytes:0;
}
static int stop_posted_rx(void) {
    /* The producer barrier is already acknowledged. Cancel pending descriptors,
     * drain the active write tail, and reclaim every completion before disable. */
    if(!release_borrowed_rx(0)) return 0;
    write64(DMA_BASE,VALENCE_NET_DMA_RX_STOP,1);
    uint64_t start=now(0);
    int valid=1;
    for(;;) {
        uint64_t status=read64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_STATUS);
        if(!queue_owned(status)) break;
        if(((status>>8)&255) && complete_posted_rx(0,0)<0) valid=0;
        if(now(0)-start>=CPU_HZ/5) return 0;
    }
    write64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_CONTROL,0);
    if((read64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_CONTROL)&1) ||
       (read64(DMA_BASE,0x48)&1)) return 0;
    posted_mode=0; posted_owned=0;
    return valid;
}
#endif
static int stop_rx(void) {
    /* PRECONDITION: GMAC_RX_STOP.DRAINED is an acknowledged producer barrier.
     * No further data/status can appear. RX_STOP alone is NOT that barrier. */
#if NETBOOT_POSTED_RX
    if(posted_mode) {
        if(!stop_posted_rx()) return 0;
    } else
#endif
    if(read64(DMA_BASE,0x48)&1) {
        write64(DMA_BASE,0x90,1);
        if(!wait_bits(DMA_BASE,0x48,1,0,CPU_HZ/5)) return 0;
    }
    write64(DMA_BASE,0x40,2); armed=0; return 1;
}
int board_netboot_quiet(void) {
    if(!active) { armed=0; return 1; }
    begin(NB_RX_TX_DRAIN);
    write64(DMA_BASE,0x08,0); write64(MAC_BASE,VGMAC_IRQ_ENABLE,0);
    /* Busy-safe admission request. Keep clocks, FIFO state and DMA consumer
     * alive until admitted frames, CDC/prefetch and adapter status have drained.
     * New wire traffic cannot extend this bounded wait after admission closes. */
    write64(MAC_BASE,VGMAC_RX_STOP,VGMAC_RX_STOP_REQUEST);
#if NETBOOT_POSTED_RX
    /* Protocol consumption has ended before quiet(). Release its retained head
     * before draining subsequent frames, never behind their FIFO completions. */
    if(posted_mode && !release_borrowed_rx(1))return failed("rx_queue_owner");
#endif
    uint64_t start=now(0);
    for(;;) {
        uint64_t mac_stop=read64(MAC_BASE,VGMAC_RX_STOP);
        if((mac_stop&3)==3) break;
#if NETBOOT_POSTED_RX
        if(posted_mode) {
            uint64_t queue=read64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_STATUS);
            if((queue>>8)&255) {
                ++drained_frames;
                if(complete_posted_rx(0,1)<0) return failed("rx_queue_owner");
            }
        } else
#endif
        {
            uint64_t rx=read64(DMA_BASE,0x48);
            if(!(rx&1)) {
                if(rx&2) ++drained_frames;
                arm_rx(); /* completed frames are discarded only in reserved scratch */
            }
        }
        if(now(0)-start>=CPU_HZ/5) return failed("producer_drain_timeout");
    }
    if(!stop_rx()) return failed("rx_dma_stop_timeout");
    if(!wait_bits(DMA_BASE,0x28,1,0,CPU_HZ/5)) return failed("tx_dma_timeout");
    if(!wait_bits(MAC_BASE,VGMAC_STATUS,6,0,CPU_HZ/5)) return failed("mac_tail_timeout");
    drain_ticks+=now(0)-stage_start; ended(now(0)-stage_start);
    begin(NB_MAC_STOP);
    /* Admission is closed and all busy tails are gone: CONTROL cannot race a
     * newly admitted frame, and no FIFO/reset/clock-gate shortcut is involved. */
    write64(MAC_BASE,VGMAC_CONTROL,0);
    if(read64(MAC_BASE,VGMAC_CONTROL)!=0 ||
       !wait_bits(MAC_BASE,VGMAC_STATUS,6,0,CPU_HZ/5)) return failed("mac_disable_timeout");
    write64(DMA_BASE,0x20,2); fence(); active=0; armed=0;
    mac_stop_ticks+=now(0)-stage_start; ended(now(0)-stage_start); return 1;
}
static int mdio(unsigned reg,int write,unsigned value) {
    if(!wait_bits(MAC_BASE,0x80,1,0,CPU_HZ/50)) return -1;
    write64(MAC_BASE,0x78,value | ((uint64_t)write<<16) | (1UL<<17) |
            (1UL<<18) | ((uint64_t)reg<<23)); /* board PHY address 1 */
    if(!wait_bits(MAC_BASE,0x80,3,2,CPU_HZ/50)) return -1;
    uint64_t result=read64(MAC_BASE,0x88);
    return result&(1UL<<16)?-1:(int)(result&65535);
}
static int initialize(void) {
    if(!firmware_ram_dma_idle())return failed("memory_dma_busy");
    /* Test existing capability locations before touching additive registers.
     * Old RTL skips networking entirely, so UART has no inherited DMA owner. */
    if(read64(DMA_BASE,0)!=0x56444d4100010001ULL ||
       read64(MAC_BASE,VGMAC_ID)!=VALENCE_GMAC_ID ||
       !(read64(MAC_BASE,VGMAC_CAP)&VGMAC_CAP_RX_STOP)) return failed("missing_mac_stop_capability");
    uint64_t capabilities=read64(DMA_BASE,VALENCE_NET_DMA_CAPABILITIES);
    if(!(capabilities&VALENCE_NET_DMA_CAP_RX_STOP)) return failed("missing_dma_stop_capability");
    hardware_probed=1;
    if(read64(DMA_BASE,0x88)<sizeof rx_frame) return failed("dma_frame_capacity");
#if NETBOOT_POSTED_RX
    unsigned hardware_slots=(unsigned)(capabilities>>VALENCE_NET_DMA_CAP_QUEUE_DEPTH_SHIFT)&255;
    posted_available=(capabilities&VALENCE_NET_DMA_CAP_RX_QUEUE) && hardware_slots &&
        hardware_slots<=16 && !(hardware_slots&(hardware_slots-1));
#endif
    active=1;
    if(!board_netboot_quiet()) return 0;
    begin(NB_INIT);
    active=1; write64(DMA_BASE,0x08,0); write64(MAC_BASE,0x38,0);
    uint64_t start=now(0);
    int high=-1, low=-1;
    /* Pad MDIO ownership is initially held by the FPGA delay initializer.
     * Poll for its release; no PHY reset and no duplicate TX delay. */
    do {
        if(abort_uart()) return 0;
        high=mdio(2,0,0); low=mdio(3,0,0);
        if(high>=0 && low>=0 && (((unsigned)high<<16 | (unsigned)low)&0xfffffff0U)==0x001cc910U) break;
    } while(now(0)-start<CPU_HZ*2);
    if(high<0 || low<0 || (((unsigned)high<<16 | (unsigned)low)&0xfffffff0U)!=0x001cc910U) return 0;
    if(mdio(31,1,0xd08)<0) return 0;
    int tx=mdio(0x11,0,0), rx=mdio(0x15,0,0), safe=0;
    if(tx>=0 && rx>=0 && mdio(0x11,1,(unsigned)tx&~256U)>=0 &&
       mdio(0x15,1,(unsigned)rx|8U)>=0) {
        tx=mdio(0x11,0,0); rx=mdio(0x15,0,0);
        safe=tx>=0 && rx>=0 && !(tx&256) && (rx&8);
    }
    if(mdio(31,1,0)<0 || !safe) return 0;
    int bmcr=mdio(0,0,0);
    if(bmcr<0) return 0;
    /* Advertise only gigabit full duplex: MAC currently implements 1G only. */
    if(mdio(4,1,1)<0 || mdio(9,1,0x200)<0 || mdio(0,1,((unsigned)bmcr&~0x0c00U)|0x1200U)<0) return 0;
    start=now(0);
    do {
        if(abort_uart()) return 0;
        (void)mdio(1,0,0); int status=mdio(1,0,0), speed=mdio(0x1a,0,0);
        if(status>=0 && (status&0x24)==0x24 && speed>=0 && (speed&0x38)==0x28) {
            write64(MAC_BASE,0x18,0x0256414c0001ULL);
            if(read64(MAC_BASE,0x18)!=0x0256414c0001ULL ||
               !wait_bits(MAC_BASE,VGMAC_STATUS,6,0,CPU_HZ/5)) return 0;
#if NETBOOT_POSTED_RX
            /* Post the whole receive window before reopening MAC admission. */
            if(posted_available && !start_posted_rx()) return 0;
#endif
            write64(MAC_BASE,0x10,11); /* TX/RX + broadcast, no promiscuous mode */
            if(read64(MAC_BASE,0x10)!=11 || !wait_bits(MAC_BASE,0x28,6,0,CPU_HZ/5)) return 0;
            write64(MAC_BASE,VGMAC_RX_STOP,0);
            return !(read64(MAC_BASE,VGMAC_RX_STOP)&VGMAC_RX_STOP_REQUEST) &&
                wait_bits(MAC_BASE,VGMAC_STATUS,6,0,CPU_HZ/5);
        }
    } while(now(0)-start<CPU_HZ*8);
    return 0;
}
static int send(void *unused,unsigned length) {
    (void)unused;
    if(!active || !length || length>sizeof tx_frame || !wait_bits(DMA_BASE,0x28,1,0,CPU_HZ/5)) return -1;
    write64(DMA_BASE,0x10,(uintptr_t)tx_frame); write64(DMA_BASE,0x18,length);
    write64(DMA_BASE,0x20,3);
    if(!wait_bits(DMA_BASE,0x28,1,0,CPU_HZ/5) || (read64(DMA_BASE,0x28)&6)!=2) return -1;
    write64(DMA_BASE,0x20,2); return 0;
}
static int recv(void *unused,uint64_t budget) {
    (void)unused;
#if NETBOOT_POSTED_RX
    if(posted_mode) {
        if(!release_borrowed_rx(1)) return -1;
        uint64_t start=now(0);
        do {
            if(abort_uart()) return -1;
            uint64_t status=read64(DMA_BASE,VALENCE_NET_DMA_RX_QUEUE_STATUS);
            if((status>>8)&255) {
                int n=complete_posted_rx(1,1);
                if(n) return n;
            }
        } while(now(0)-start<budget);
        return 0; /* timeout never relinquishes any posted descriptor */
    }
#endif
    if(!armed) {
        if(read64(DMA_BASE,0x48)&1) return -1; /* never mutate a DMA-owned descriptor */
        arm_rx();
    }
    uint64_t start=now(0);
    do {
        uint64_t status=read64(DMA_BASE,0x48);
        if(status&2) {
            unsigned n=(unsigned)read64(DMA_BASE,0x50);
            write64(DMA_BASE,0x40,2); armed=0;
            return !(status&4) && n<=sizeof rx_frame?(int)n:0;
        }
        if(abort_uart()) return -1; /* full shutdown owns the producer barrier */
    } while(now(0)-start<budget);
    /* A receive timeout does not transfer ownership or stop the consumer.
     * Keep it armed for the next poll/retry; cancellation uses quiet(). */
    return 0;
}
static uint8_t *received_frame(void *unused) {
    (void)unused;
#if NETBOOT_POSTED_RX
    if(posted_mode && borrowed_valid) return posted_rx[borrowed_slot];
#endif
    return rx_frame;
}
static int store(void *unused,uint32_t offset,const uint8_t *p,unsigned n) {
    (void)unused;
    if(offset>IMAGE_LIMIT || n>IMAGE_LIMIT-offset) return -1;
    volatile uint8_t *to=ram_pointer(offset);
    /* Frame payload alignment is arbitrary. Pack from bytes, and issue only
     * aligned wide RAM stores; prefix/tail stores preserve neighboring bytes.
     * may_alias also keeps the native byte-array oracle well-defined. */
    typedef uint64_t ram_word __attribute__((may_alias));
    while(n && ((uintptr_t)to&7)) { *to++=*p++; --n; }
    while(n>=8) {
        uint64_t word=(uint64_t)p[0] | (uint64_t)p[1]<<8 | (uint64_t)p[2]<<16 |
            (uint64_t)p[3]<<24 | (uint64_t)p[4]<<32 | (uint64_t)p[5]<<40 |
            (uint64_t)p[6]<<48 | (uint64_t)p[7]<<56;
        *(volatile ram_word *)to=word; to+=8; p+=8; n-=8;
    }
    while(n--) *to++=*p++;
    return 0;
}
static int prepare_verify(void *unused) {
    (void)unused;
    /* The fixed final ACK/dally has completed; no new network owner is needed. */
    if(!board_netboot_quiet())return -1;
    begin(NB_RAM_PREPARE);
    if(!firmware_ram_prepare(&ram_flush_ticks,&ram_sweep_ticks)){
        failed("memory_dma_busy");return -1;
    }
    ended(ram_flush_ticks+ram_sweep_ticks);return 0;
}
static int verify(void *unused,uint32_t length,uint32_t crc) {
    (void)unused;
    uint64_t crc_start=now(0);
    uint32_t running=0xffffffffU;
    for(uint32_t offset=0;offset<length;) {
        unsigned n=length-offset>4096?4096:length-offset;
        running=nb_crc_update(running,ram_pointer(offset),n); offset+=n;
        /* Keep UART cancellation bounded even during a multi-second full RAM
         * pass. This remains an independent readback, never the stream CRC. */
        if(abort_uart()) return -2;
    }
    ram_readback_ticks=now(0)-crc_start;
    ram_crc=running^0xffffffffU;
    ram_crc_valid=1; return ram_crc==crc?0:-1;
}
static void protocol_stage(void *unused,enum nb_stage value) {
    (void)unused;
    if(value==NB_RX && current_stage==NB_ARP) ended(now(0)-stage_start);
    if(value==NB_STREAM_CRC && current_stage==NB_RX) ended(now(0)-stage_start);
    if((value==NB_RAM_CRC || value==NB_RAM_PREPARE) && current_stage==NB_STREAM_CRC) ended(stats.crc_ticks);
    if(value==NB_RAM_PREPARE)return; /* quiet has its own stages; callback starts prepare after it */
    begin(value);
}
static void summary(void) {
    text("NB totals"); field("timebase_hz",CPU_HZ); field("init_ticks",init_ticks); field("transfer_ticks",transfer_ticks);
    field("rx_wait_ticks",stats.rx_ticks); field("copy_ticks",stats.copy_ticks);
    field("stream_crc_ticks",stats.crc_ticks); field("tx_ack_ticks",stats.tx_ticks);
    field("ram_crc_ticks",ram_readback_ticks); field("ram_flush_ticks",ram_flush_ticks); field("ram_sweep_ticks",ram_sweep_ticks); field("verify_callback_ticks",stats.verify_ticks); field("drain_ticks",drain_ticks);
    field("mac_stop_ticks",mac_stop_ticks); field("rx_frames",stats.rx_frames);
    field("rx_timeouts",stats.rx_timeouts); field("tx_frames",stats.tx_frames);
    field("retries",stats.retries); field("duplicates",stats.duplicates);
    field("block_size",stats.block_size); field("window_size",stats.window_size);
    field("acks",stats.acks); field("out_of_order",stats.out_of_order);
    field("final_ack_ticks",stats.final_ack_ticks);
#if NETBOOT_POSTED_RX
    field("posted_rx",posted_used); field("posted_rx_frames",posted_frames);
    field("posted_rx_drops",posted_drops); field("posted_rx_copy_ticks",posted_copy_ticks);
#endif
    field("drain_completions_rearmed",drained_frames); field("length",stats.received); text("\r\n");
}
void board_netboot_jump(uint32_t entry,uint32_t length) {
    text("NB stage=jump"); hexfield("entry",entry); field("length",length);
    field("tick",now(0)); text("\r\n");
}
int board_netboot(uint32_t *entry,uint32_t *length) {
    stats=(struct nb_stats){0}; pending_command=0; ram_crc_valid=0; failure_reported=0;
    init_ticks=drain_ticks=mac_stop_ticks=transfer_ticks=0; ram_flush_ticks=ram_sweep_ticks=ram_readback_ticks=0; drained_frames=0;
#if NETBOOT_POSTED_RX
    posted_used=0; posted_frames=posted_drops=0; posted_copy_ticks=0;
#endif
    begin(NB_INIT); text("NB time_source=rdtime"); field("timebase_hz",CPU_HZ); text("\r\n");
    uint64_t init_start=now(0);
    if(!initialize()) {
        init_ticks=now(0)-init_start;
        if(!failure_reported) failed(pending_command?"uart_cancel":"initialize");
        (void)board_netboot_quiet(); summary(); return 0;
    }
    init_ticks=now(0)-init_start; ended(init_ticks);
    struct nb_ops ops={ .context=0,.tx=tx_frame,.rx=rx_frame,
        .mac={2,0x56,0x41,0x4c,0,1},.ip=NETBOOT_IP,.server_ip=NETBOOT_SERVER,
        .base=RAM_BASE,.limit=IMAGE_LIMIT,.hz=CPU_HZ,
        .now=now,.send=send,.recv=recv,.store=store,.verify=verify,
        .stats=&stats,.stage=protocol_stage,.received_frame=received_frame,.prepare_verify=prepare_verify
#if NETBOOT_POSTED_RX
        ,.request_blksize=posted_mode?NETBOOT_BLOCK_BYTES:0,
        .request_windowsize=posted_mode?negotiated_window_cap:0
#endif
    };
    uint32_t verified_entry=0, verified_length=0;
    uint64_t transfer_start=now(0);
    int good=nb_tftp(&ops,NETBOOT_FILE,&verified_entry,&verified_length);
    transfer_ticks=now(0)-transfer_start;
    if(good) ended(ram_readback_ticks);
    else if(!failure_reported) {
        current_stage=stats.stage;
        static const char *const reasons[]={"none","send","uart_or_rx_abort","retry_limit",
            "server_error","header","range","store","length","stream_crc","ram_crc","bad_options","ram_prepare"};
        failed((unsigned)stats.failure<sizeof reasons/sizeof reasons[0]?reasons[stats.failure]:"unknown");
    }
    int quiet=board_netboot_quiet(); summary();
    if(good && abort_uart()) { text("NB cancel before_jump\r\n"); good=0; }
    if(!quiet || !good) return 0;
    *entry=verified_entry; *length=verified_length; return 1;
}

uint32_t board_netboot_verified_crc(void) { return ram_crc_valid ? ram_crc : 0; }

void board_netboot_info(void) {
    if(!hardware_probed){text("HW network unprobed; n validates MMIO identity before network-info reads\r\n");return;}
    text("HW MMIO");hexfield("GMAC_ID",read64(MAC_BASE,VGMAC_ID));hexfield("GMAC_CAP",read64(MAC_BASE,VGMAC_CAP));
    hexfield("NET_DMA_ID",read64(DMA_BASE,0));hexfield("NET_DMA_CAP",read64(DMA_BASE,VALENCE_NET_DMA_CAPABILITIES));text("\r\n");
}
