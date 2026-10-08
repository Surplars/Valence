#ifndef VALENCE_GMAC_H
#define VALENCE_GMAC_H
#include <stdint.h>
/* Self-designed TL-UL control ABI V1. This is not PG138/xilinx_axienet ABI.
 * The current foundation is not yet connected to a board MAC/PHY. */
#define VALENCE_GMAC_BASE UINT64_C(0x10040000)
#define VALENCE_GMAC_PORT_STRIDE UINT64_C(0x1000)
#define VALENCE_GMAC_ID UINT64_C(0x56474d4100010001)
#define VGMAC_ID 0x00
#define VGMAC_CAP 0x08
#define VGMAC_CONTROL 0x10
#define VGMAC_MAC_ADDRESS 0x18
#define VGMAC_MAX_FRAME_BYTES 0x20
#define VGMAC_STATUS 0x28
#define VGMAC_IRQ_PENDING 0x30
#define VGMAC_IRQ_ENABLE 0x38
#define VGMAC_TX_FRAMES 0x40
#define VGMAC_RX_FRAMES 0x48
#define VGMAC_RX_DROPS 0x50
#define VGMAC_RX_BAD_FCS 0x58
#define VGMAC_TX_BYTES 0x60
#define VGMAC_RX_BYTES 0x68
#define VGMAC_CLEAR_STATS 0x70
#define VGMAC_MDIO_COMMAND 0x78
#define VGMAC_MDIO_STATUS 0x80
#define VGMAC_MDIO_RESULT 0x88
/* Additive stop barrier. Only access RX_STOP when CAP bit8 is set.
 * Full-width write1 closes RX admission without cancelling an admitted frame;
 * write0 reopens it. Read bit0=requested, bit1=drained (acknowledged producer
 * barrier over admitted frames, CDC/FIFO/prefetch and adapter data/status).
 * DMA DDR writes are separate: drain/stop the DMA only AFTER this barrier.
 * Keep a scratch RX descriptor consuming while awaiting drained. */
#define VGMAC_CAP_RX_STOP (UINT64_C(1) << 8)
#define VGMAC_CAP_TRI_SPEED (UINT64_C(1) << 10)
#define VGMAC_CAP_MANAGED_PHY (UINT64_C(1) << 11)
#define VGMAC_CAP_DROP_DIAGNOSTICS (UINT64_C(1) << 12)
#define VGMAC_MEDIA_STATUS 0x98
#define VGMAC_PHY_ERRORS 0xa0
#define VGMAC_PHY_POLLS 0xa8
#define VGMAC_RX_DROP_BANK_FULL 0xb0
#define VGMAC_RX_DROP_ADMISSION 0xb8
#define VGMAC_RX_DROP_PREAMBLE 0xc0
#define VGMAC_RX_DROP_FCS 0xc8
#define VGMAC_RX_DROP_LENGTH 0xd0
#define VGMAC_RX_DROP_ADDRESS 0xd8
#define VGMAC_RX_DROP_PHY_ERROR 0xe0
#define VGMAC_RX_DROP_LINK_ABORT 0xe8
#define VGMAC_TX_LINK_ABORTS 0xf0
#define VGMAC_RX_FIFO_STALL_CYCLES 0xf8
#define VGMAC_TX_FIFO_STALL_CYCLES 0x100
#define VGMAC_RX_ODD_NIBBLES 0x108
#define VGMAC_PHY_TRANSITION_ERRORS 0x110
#define VGMAC_PHY_CONTROL 0x118
#define VGMAC_RX_INGRESS_OVERFLOWS 0x120
#define VGMAC_RX_INGRESS_SKIPPED 0x128
#define VGMAC_MEDIA_INITIALIZED UINT64_C(1)
#define VGMAC_MEDIA_PHY_LINK (UINT64_C(1) << 1)
#define VGMAC_MEDIA_PENDING (UINT64_C(1) << 6)
#define VGMAC_MEDIA_TIMEOUT (UINT64_C(1) << 7)
#define VGMAC_MEDIA_FAULT_MASK (UINT64_C(15) << 8)
#define VGMAC_MEDIA_READY (UINT64_C(1) << 12)
#define VGMAC_MEDIA_EXTENSION_VERSION UINT64_C(1)
/* CAP.MANAGED_PHY changes PHY ownership only on the opt-in profile. Software
 * must not reset/configure the PHY or attach an independently writing phylib
 * instance. Base-page diagnostic reads are serialized; writes/vendor-page
 * accesses return noAck. PHY_CONTROL full-width write1 requests reinitialize.
 * MEDIA_STATUS version[63:56], requested speed[3:2], applied speed[5:4]:
 * 0=10, 1=100, 2=1000; bit12 means both media domains committed the same rate.
 * Diagnostic counters are additive64 and clear with CLEAR_STATS; PHY counters
 * are lifetime32 pairs (errors: noAck,verify; polls: linkChange,polls;
 * transition errors: unsupported,timeout). No buffer reset on transition. */
#define VGMAC_RX_STOP 0x90
#define VGMAC_RX_STOP_REQUEST UINT64_C(1)
#define VGMAC_RX_STOP_DRAINED UINT64_C(2)
#define VGMAC_TX_ENABLE UINT64_C(1)
#define VGMAC_RX_ENABLE UINT64_C(2)
#define VGMAC_PROMISCUOUS UINT64_C(4)
#define VGMAC_BROADCAST_ENABLE UINT64_C(8)
/* CONTROL/MAC_ADDRESS writes require TX and RX idle. MAC address byte zero
 * (first octet on wire) is bits[47:40], e.g. 02:00:00:00:00:01 = 0x020000000001.
 * IRQ_PENDING W1C bits 0..6: TX, RX, drop, bad FCS, underflow, link, MDIO.
 * MDIO_STATUS: busy bit0, done bit1. RESULT: data[15:0], noAck bit16.
 * A command must be a full-width 64-bit write; poll busy before submitting. */
static inline uint64_t valence_gmac_mdio_command(unsigned phy, unsigned reg,
    unsigned write, uint16_t data) {
    return (uint64_t)data | ((uint64_t)(write & 1) << 16) | (UINT64_C(1) << 17) |
        ((uint64_t)(phy & 31) << 18) | ((uint64_t)(reg & 31) << 23);
}
static inline volatile uint64_t *valence_gmac_register(unsigned port, unsigned offset) {
    return (volatile uint64_t *)(uintptr_t)(VALENCE_GMAC_BASE +
        port * VALENCE_GMAC_PORT_STRIDE + offset);
}
#endif
