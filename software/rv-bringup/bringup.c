#include "i1_boot_protocol.h"

static inline uint64_t cycle(void) { uint64_t v; __asm__ volatile("csrr %0, mcycle" : "=r"(v)); return v; }
static inline uint64_t retired(void) { uint64_t v; __asm__ volatile("csrr %0, minstret" : "=r"(v)); return v; }
static void publish(volatile I1BootMailbox *mailbox, uint32_t state)
{
    __asm__ volatile("fence rw, rw" ::: "memory");
    mailbox->state = state;
}
int main(void)
{
    volatile I1BootMailbox *m = (volatile I1BootMailbox *)(uintptr_t)I1_RV_BOOT_MAILBOX;
    if (m->magic != I1_BOOT_MAGIC || m->abi != I1_BOOT_ABI ||
        m->image_bytes == 0 || m->image_bytes > I1_BOOT_IMAGE_MAX_BYTES) {
        m->error = I1_BOOT_BAD_HEADER;
        publish(m, I1_BOOT_FAILED);
        return 0;
    }
    uint64_t first_cycle = cycle(), first_retired = retired();
    __asm__ volatile("csrr %0, mhartid" : "=r"(m->hart_id));
    __asm__ volatile("csrr %0, misa" : "=r"(m->misa));
    publish(m, I1_BOOT_RUNNING);
    m->observed_crc32 = I1BootCrc32((const uint8_t *)(uintptr_t)I1_RV_DDR_BASE, m->image_bytes);
    if (m->observed_crc32 != m->image_crc32) {
        m->error = I1_BOOT_BAD_CRC;
        publish(m, I1_BOOT_FAILED);
        return 0;
    }
    if (m->flags & I1_BOOT_FORCE_BREAKPOINT) {
        __asm__ volatile(".globl __i1_breakpoint_probe\n__i1_breakpoint_probe: ebreak");
    }
    m->kernel_checksum = I1BootKernel(m->seed, m->iterations);
    m->cycles = cycle() - first_cycle;
    m->instructions = retired() - first_retired;
    m->error = 0;
    publish(m, I1_BOOT_PASSED);
    return 0;
}
