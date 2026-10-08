#ifndef VALENCE_ETHERNET_DMA_H
#define VALENCE_ETHERNET_DMA_H
#include <stdint.h>

/* V1 simple-descriptor ABI, not Xilinx AXI DMA. MAC/PHY setup is separate.
 * Buffer physical addresses must be 8-byte aligned and remain CPU-owned until
 * submitted, then DMA-owned until completion. No SG/IOMMU; <=2048 bytes/frame.
 */
#define VALENCE_NET_DMA_BASE 0x10002000UL
#define VALENCE_NET_DMA_IRQ 6
#define VALENCE_NET_DMA_BUSY 1UL
#define VALENCE_NET_DMA_DONE 2UL
#define VALENCE_NET_DMA_ERROR 4UL
/* Additive 2026-10-06 ABI: new bit only. Read CAP(0x98) bit 0 before use
 * on a platform whose address map guarantees these registers exist.
 * RX_STOP(0x90)=1 stops an empty wait immediately, discards/drains a partial
 * frame, and drains accepted DDR writes. Poll BUSY=0 before reclaiming memory.
 * Not a hard abort: a stalled memory target or incomplete stream can still wait.
 */
#define VALENCE_NET_DMA_RX_STOP 0x90
#define VALENCE_NET_DMA_CAPABILITIES 0x98
/* CAP[15:8] posted slots; CAP[23:16] total ordered memory credits. */
#define VALENCE_NET_DMA_CAP_MEMORY_CREDITS_SHIFT 16
#define VALENCE_NET_DMA_CAP_RX_STOP 1UL
#define VALENCE_NET_DMA_CAP_RX_QUEUE 2UL
#define VALENCE_NET_DMA_CAP_QUEUE_DEPTH_SHIFT 8
/* Additive opt-in posted RX ABI, preserving the legacy ID and descriptors.
 * CAP bit 1 advertises it; CAP[15:8] is the owned-descriptor limit (currently 4).
 * QUEUE_CONTROL bit 0 changes only while idle with no owned descriptors.
 * Stage ADDRESS/CAPACITY then POST=1 while enabled and with free credit. Credit
 * counts pending + active + retained completions. A descriptor and its buffer
 * remain DMA-owned until COMPLETE_POP=1, even after its completion is visible.
 * COMPLETE_ADDRESS/RESULT describe the oldest completion, stable until POP.
 * RESULT[15:0]=bytes, bit16=error; unused bits are zero. QSTATUS[7:0]=pending,
 * [15:8]=completion count, bit16=active, bit17=RX_STOP latched. RX_STOP blocks
 * new posts/launches, safely drains the active frame/writes, then emits error
 * completions for pending slots. Pop all completions before disable, which
 * clears STOP. Reenable begins an empty queue. QUEUE_CONTROL bit1 is reserved.
 * Legacy RX START is unavailable while queue mode is enabled.
 */
#define VALENCE_NET_DMA_RX_POST_ADDRESS 0xa0
#define VALENCE_NET_DMA_RX_POST_CAPACITY 0xa8
#define VALENCE_NET_DMA_RX_POST 0xb0
#define VALENCE_NET_DMA_RX_QUEUE_CONTROL 0xb8
#define VALENCE_NET_DMA_RX_QUEUE_STATUS 0xc0
#define VALENCE_NET_DMA_RX_COMPLETE_ADDRESS 0xc8
#define VALENCE_NET_DMA_RX_COMPLETE_RESULT 0xd0
#define VALENCE_NET_DMA_RX_COMPLETE_POP 0xd8
#define VALENCE_NET_DMA_RX_COMPLETE_ERROR (1UL<<16)
#define VALENCE_NET_DMA_RX_QUEUE_STOPPED (1UL<<17)
static inline void valence_dma_fence(void) {
    __asm__ volatile("fence iorw,iorw" ::: "memory");
}
static inline uint64_t valence_net_read(unsigned offset) {
    return *(volatile uint64_t *)(VALENCE_NET_DMA_BASE + offset);
}
static inline void valence_net_write(unsigned offset, uint64_t value) {
    *(volatile uint64_t *)(VALENCE_NET_DMA_BASE + offset) = value;
}
static inline void valence_net_interrupts(unsigned tx, unsigned rx) {
    valence_net_write(0x08, (!!tx) | ((!!rx) << 1));
}
static inline int valence_net_tx_submit(uintptr_t address, unsigned bytes) {
    if ((address & 7) || !bytes || bytes > 2048) return -1;
    if (valence_net_read(0x28) & VALENCE_NET_DMA_BUSY) return -2;
    valence_dma_fence();
    valence_net_write(0x10, address);
    valence_net_write(0x18, bytes);
    valence_net_write(0x20, 3); /* ack previous completion, start */
    valence_dma_fence();
    return 0;
}
static inline int valence_net_rx_submit(uintptr_t address, unsigned capacity) {
    if ((address & 7) || !capacity || capacity > 2048) return -1;
    if (valence_net_read(0x48) & VALENCE_NET_DMA_BUSY) return -2;
    valence_dma_fence();
    valence_net_write(0x30, address);
    valence_net_write(0x38, capacity);
    valence_net_write(0x40, 3);
    valence_dma_fence();
    return 0;
}
/* 0=pending, 1=success, -1=error. Nonblocking: caller supplies timeout policy. */
static inline int valence_net_tx_poll(void) {
    uint64_t status = valence_net_read(0x28);
    if (!(status & VALENCE_NET_DMA_DONE)) return 0;
    valence_dma_fence();
    return status & VALENCE_NET_DMA_ERROR ? -1 : 1;
}
static inline int valence_net_rx_poll(unsigned *bytes) {
    uint64_t status = valence_net_read(0x48);
    if (!(status & VALENCE_NET_DMA_DONE)) return 0;
    valence_dma_fence();
    if (bytes) *bytes = (unsigned)valence_net_read(0x50);
    return status & VALENCE_NET_DMA_ERROR ? -1 : 1;
}
static inline void valence_net_ack_tx(void) { valence_net_write(0x20, 2); }
static inline void valence_net_ack_rx(void) { valence_net_write(0x40, 2); }
#endif
