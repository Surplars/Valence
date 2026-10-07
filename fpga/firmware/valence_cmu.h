#ifndef VALENCE_CMU_H
#define VALENCE_CMU_H
#include <stdint.h>
/* Optional CMU V1; do not probe unless the platform advertises its presence.
 * Offsets are 64-bit words; naturally aligned 8/16/32/64-bit accesses are legal.
 * Existing board CPU/TIME/UART/DDR/GMAC resources are protected in this release.
 * CLOCK_ENABLE reports a command, never a measured frequency/physical gate ACK.
 */
#define VALENCE_CMU_BASE UINT64_C(0x10080000)
#define VALENCE_CMU_ID UINT64_C(0x56434d5500010001)
enum valence_cmu_offset {
    CMU_ID_VERSION=0x00, CMU_CAPABILITIES=0x08, CMU_PRESENT=0x10, CMU_GATEABLE=0x18,
    CMU_STOP_REQUEST=0x20, CMU_CLOCK_ENABLE=0x28, CMU_STOPPED=0x30, CMU_QUIESCE=0x38,
    CMU_ISOLATE=0x40, CMU_ADMISSION=0x48, CMU_WAKE_PENDING=0x50, CMU_WAKE_ENABLE=0x58,
    CMU_WAKE_SET=0x60, CMU_FAULT_PENDING=0x68, CMU_IRQ_ENABLE=0x70, CMU_IRQ_STATUS=0x78
};
enum valence_cmu_resource { CMU_AON=0, CMU_CPU=1, CMU_TIME=2, CMU_UART=3,
    CMU_DDR_UI=4, CMU_GMAC_TX=5, CMU_GMAC_RX=6, CMU_FIRST_MANAGED=7 };
static inline uint64_t valence_cmu_read(unsigned offset) {
    return *(volatile uint64_t *)(uintptr_t)(VALENCE_CMU_BASE+offset);
}
static inline void valence_cmu_write(unsigned offset, uint64_t value) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    *(volatile uint64_t *)(uintptr_t)(VALENCE_CMU_BASE+offset)=value;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}
/* Never blindly RMW W1C: clear only the events that the caller actually handled.
 * Stop completion is polled with a caller-owned deadline; a fault fails open.
 * STOP_REQUEST is shared RW state: callers must serialize its RMW operations.
 * WAKE_SET is W1S, also clears STOP; wait for ISOLATE to clear before access.
 */
#endif
