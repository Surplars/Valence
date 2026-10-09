#ifndef VALENCE_JTAG_DOWNLOAD_H
#define VALENCE_JTAG_DOWNLOAD_H
#include <stdint.h>

/* Optional BootROM cooperative downloader, not a RISC-V Debug Module.
 * Every CPU register access is an aligned, full-width 64-bit transaction.
 * Host writes go through the coherent DMA path; fences alone are not a
 * substitute for firmware_ram_prepare and the independent RAM CRC below. */
#define JTAG_DOWNLOAD_BASE 0x10003000UL
enum jtag_download_register {
    JTAG_STATUS = 0, JTAG_COMMAND = 8, JTAG_ENTRY = 16, JTAG_LENGTH = 24,
    JTAG_CRC = 32, JTAG_GENERATION = 40, JTAG_RAM_BASE = 48, JTAG_RAM_END = 56
};
enum jtag_download_status {
    JTAG_ARMED = 1, JTAG_COMMITTED = 2, JTAG_CANCELLED = 4,
    JTAG_BUSY = 8, JTAG_FAULT = 16, JTAG_LINK_UP = 32, JTAG_CLAIMED = 64
};
enum jtag_download_command { JTAG_OPEN = 1, JTAG_CLOSE = 2, JTAG_CLAIM = 3 };

#ifdef BOOTROM_TEST
extern uint64_t boot_test_jtag_read(unsigned offset);
extern void boot_test_jtag_write(unsigned offset, uint64_t value);
extern void boot_test_jtag_fence(void);
#endif
static uint64_t jtag_read(unsigned offset) {
#ifdef BOOTROM_TEST
    return boot_test_jtag_read(offset);
#else
    uint64_t value;
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    value = *(volatile uint64_t *)(JTAG_DOWNLOAD_BASE + offset);
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    return value;
#endif
}
static void jtag_write(unsigned offset, uint64_t value) {
#ifdef BOOTROM_TEST
    boot_test_jtag_write(offset, value);
#else
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    *(volatile uint64_t *)(JTAG_DOWNLOAD_BASE + offset) = value;
    __asm__ volatile("fence iorw,iorw" ::: "memory");
#endif
}
static void jtag_image_fence(void) {
#ifdef BOOTROM_TEST
    boot_test_jtag_fence();
#else
    __asm__ volatile("fence rw,rw\nfence.i\nfence rw,rw" ::: "memory");
#endif
}
#endif
