#ifndef VALENCE_RAM_VERIFY_H
#define VALENCE_RAM_VERIFY_H
#include <stdint.h>
#include "board_memory.h"
/* Current supported monitor/cache profiles: <=32KiB,64B lines,1 or2 ways.
 * Dirty flush invalidates dirty lines only. A64KiB tail sweep removes every
 * prior line outside the sweep. If the image overlaps the sweep, its >=64KiB
 * preceding prefix replaces sweep lines before the CRC reaches that tail.
 * Two sweeps are conservative; each is1024 distinct lines,4 tags per2way set.
 * Read-only scratch does not reserve or overwrite payload/DTB bytes.
 */
#define RAM_VERIFY_SWEEP_BYTES 65536UL
_Static_assert(BOARD_MONITOR_BASE-RAM_BASE>=2*RAM_VERIFY_SWEEP_BYTES,
               "RAM verification requires64KiB tail plus64KiB image prefix");
#if defined(BOOTROM_TEST) || defined(NETBOOT_BOARD_TEST)
extern int firmware_ram_dma_idle(void);
extern int firmware_ram_prepare(uint64_t *flush_ticks,uint64_t *sweep_ticks);
#else
static inline int firmware_ram_dma_idle(void) {
    __asm__ volatile("fence iorw,iorw":::"memory");
    return !(*(volatile uint64_t *)0x10001020UL&1);
}
static __attribute__((noinline)) int firmware_ram_prepare(uint64_t *flush_ticks,uint64_t *sweep_ticks) {
    if(!firmware_ram_dma_idle())return 0;
    uint64_t start,flushed,done,consume=0;
    __asm__ volatile("rdtime %0":"=r"(start)::"memory");
    /* On this SoC fence.i = private dirty writeback/invalidate, then home drain.
     * Do not replace this with ordinary MMIO ordering or volatile accesses. */
    __asm__ volatile("fence rw,rw\nfence.i\nfence rw,rw\nrdtime %0":"=r"(flushed)::"memory");
    for(unsigned pass=0;pass<2;pass++)
        for(uintptr_t address=BOARD_MONITOR_BASE-RAM_VERIFY_SWEEP_BYTES;
            address<BOARD_MONITOR_BASE;address+=64)
            consume^=*(volatile const uint64_t *)address;
    __asm__ volatile(""::"r"(consume):"memory");
    __asm__ volatile("fence rw,rw\nrdtime %0":"=r"(done)::"memory");
    *flush_ticks=flushed-start;*sweep_ticks=done-flushed;return 1;
}
#endif
#endif
