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
