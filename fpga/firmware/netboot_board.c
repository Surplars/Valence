#include "netboot.h"
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
#define DMA_BASE 0x10002000UL
#define MAC_BASE 0x10040000UL
#define UART ((volatile uint8_t *)0x10000000UL)
/* These lie in the monitor's reserved 16 KiB, excluded by IMAGE_LIMIT and DT. */
static uint8_t tx_frame[2048] __attribute__((aligned(64)));
static uint8_t rx_frame[2048] __attribute__((aligned(64)));
static int active, armed, pending_command;
/* GCC may lower aggregate initialization to memcpy even with -ffreestanding. */
void *memcpy(void *to,const void *from,size_t n) {
    uint8_t *d=to; const uint8_t *s=from;
    for(size_t i=0;i<n;++i) d[i]=s[i];
    return to;
}
static uint64_t now(void *unused) {
    (void)unused; uint64_t value; __asm__ volatile("rdtime %0":"=r"(value)); return value;
}
static void fence(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static uint64_t read64(uintptr_t base,unsigned offset) {
    uint64_t value=*(volatile uint64_t *)(base+offset); fence(); return value;
}
static void write64(uintptr_t base,unsigned offset,uint64_t value) {
    fence(); *(volatile uint64_t *)(base+offset)=value; fence();
}
static int wait_bits(uintptr_t base,unsigned off,uint64_t mask,uint64_t value,uint64_t budget) {
    uint64_t start=now(0);
    do { if((read64(base,off)&mask)==value) return 1; } while(now(0)-start<budget);
    return 0;
}
static int abort_uart(void) {
    if(UART[5]&1) {
        unsigned c=UART[0];
        if(c=='d') { pending_command='d'; return 1; }
    }
    return 0;
}
int board_netboot_command(void) {
    int c=pending_command; pending_command=0; return c;
}
static int stop_rx(void) {
    if(read64(DMA_BASE,0x48)&1) {
        write64(DMA_BASE,0x90,1);
        if(!wait_bits(DMA_BASE,0x48,1,0,CPU_HZ/5)) return 0;
    }
    write64(DMA_BASE,0x40,2); armed=0; return 1;
}
int board_netboot_quiet(void) {
    if(!active) return 1;
    write64(DMA_BASE,0x08,0); write64(MAC_BASE,0x38,0);
    if(!stop_rx() || !wait_bits(DMA_BASE,0x28,1,0,CPU_HZ/5) ||
       !wait_bits(MAC_BASE,0x28,6,0,CPU_HZ/5)) return 0;
    write64(MAC_BASE,0x10,0);
    if(read64(MAC_BASE,0x10)!=0 || !wait_bits(MAC_BASE,0x28,6,0,CPU_HZ/5)) return 0;
    write64(DMA_BASE,0x20,2); fence(); active=0; return 1;
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
    /* This build targets the new additive RX_STOP ABI; do not flash its ROM
     * into an older bit. The old driver still accepts the unchanged ID. */
    if(read64(DMA_BASE,0)!=0x56444d4100010001ULL ||
       read64(MAC_BASE,0)!=0x56474d4100010001ULL || !(read64(DMA_BASE,0x98)&1)) return 0;
    active=1;
    if(!board_netboot_quiet()) return 0;
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
            write64(MAC_BASE,0x10,11); /* TX/RX + broadcast, no promiscuous mode */
            return read64(MAC_BASE,0x10)==11 && wait_bits(MAC_BASE,0x28,6,0,CPU_HZ/5);
        }
    } while(now(0)-start<CPU_HZ*8);
    return 0;
}
static int send(void *unused,unsigned length) {
    (void)unused;
    if(!length || length>sizeof tx_frame || !wait_bits(DMA_BASE,0x28,1,0,CPU_HZ/5)) return -1;
    write64(DMA_BASE,0x10,(uintptr_t)tx_frame); write64(DMA_BASE,0x18,length);
    write64(DMA_BASE,0x20,3);
    if(!wait_bits(DMA_BASE,0x28,1,0,CPU_HZ/5) || (read64(DMA_BASE,0x28)&6)!=2) return -1;
    write64(DMA_BASE,0x20,2); return 0;
}
static int recv(void *unused,uint64_t budget) {
    (void)unused;
    if(!armed) {
        write64(DMA_BASE,0x30,(uintptr_t)rx_frame); write64(DMA_BASE,0x38,sizeof rx_frame);
        write64(DMA_BASE,0x40,3); armed=1;
    }
    uint64_t start=now(0);
    do {
        uint64_t status=read64(DMA_BASE,0x48);
        if(status&2) {
            unsigned n=(unsigned)read64(DMA_BASE,0x50);
            write64(DMA_BASE,0x40,2); armed=0;
            return !(status&4) && n<=sizeof rx_frame?(int)n:0;
        }
        if(abort_uart()) { (void)stop_rx(); return -1; }
    } while(now(0)-start<budget);
    return stop_rx()?0:-1;
}
static int store(void *unused,uint32_t offset,const uint8_t *p,unsigned n) {
    (void)unused;
    if(offset>IMAGE_LIMIT || n>IMAGE_LIMIT-offset) return -1;
    volatile uint8_t *to=(volatile uint8_t *)(RAM_BASE+offset);
    for(unsigned i=0;i<n;++i) to[i]=p[i];
    return 0;
}
static int verify(void *unused,uint32_t length,uint32_t crc) {
    (void)unused; fence();
    return (nb_crc_update(0xffffffffU,(const uint8_t *)RAM_BASE,length)^0xffffffffU)==crc?0:-1;
}
int board_netboot(uint32_t *entry,uint32_t *length) {
    if(!initialize()) { (void)board_netboot_quiet(); return 0; }
    struct nb_ops ops={ .context=0,.tx=tx_frame,.rx=rx_frame,
        .mac={2,0x56,0x41,0x4c,0,1},.ip=NETBOOT_IP,.server_ip=NETBOOT_SERVER,
        .base=RAM_BASE,.limit=IMAGE_LIMIT,.hz=CPU_HZ,
        .now=now,.send=send,.recv=recv,.store=store,.verify=verify };
    int good=nb_tftp(&ops,NETBOOT_FILE,entry,length);
    return board_netboot_quiet() && good;
}
