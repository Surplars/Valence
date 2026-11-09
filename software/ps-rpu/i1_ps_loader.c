#include "i1_ps_loader.h"
#include "xil_cache.h"
#include "xil_mem.h"
#include "xstatus.h"

int I1PsHoldForColdLaunch(XGpioPs *gpio)
{
    XGpioPs_SetDirectionPin(gpio, I1_PS_STARTED_GPIO, 0U);
    if (XGpioPs_ReadPin(gpio, I1_PS_STARTED_GPIO)) return XST_DEVICE_BUSY;

    /* Set output latches before enabling the drivers, keeping reset held. */
    XGpioPs_WritePin(gpio, I1_PS_START_GPIO, 0U);
    XGpioPs_WritePin(gpio, I1_PS_DDR_READY_GPIO, 0U);
    XGpioPs_SetDirectionPin(gpio, I1_PS_START_GPIO, 1U);
    XGpioPs_SetDirectionPin(gpio, I1_PS_DDR_READY_GPIO, 1U);
    XGpioPs_SetOutputEnablePin(gpio, I1_PS_START_GPIO, 1U);
    XGpioPs_SetOutputEnablePin(gpio, I1_PS_DDR_READY_GPIO, 1U);

    return XST_SUCCESS;
}

int I1PsLoadAndStart(XGpioPs *gpio, const void *image, u32 bytes)
{
    if (bytes == 0U || bytes > I1_BOOT_IMAGE_MAX_BYTES) return XST_INVALID_PARAM;
    int status = I1PsHoldForColdLaunch(gpio);
    if (status != XST_SUCCESS) return status;

    /* HP is noncoherent: publish all image bytes to DDR before releasing PL. */
    Xil_MemCpy((void *)(UINTPTR)I1_PS_DDR_BASE, image, bytes);
    Xil_DCacheFlushRange((INTPTR)I1_PS_DDR_BASE, bytes);
    I1BootMailbox *m = (I1BootMailbox *)(UINTPTR)I1_PS_BOOT_MAILBOX;
    uint8_t *raw = (uint8_t *)m;
    for (unsigned i = 0; i < sizeof(*m); ++i) raw[i] = 0;
    m->magic = I1_BOOT_MAGIC; m->abi = I1_BOOT_ABI;
    m->image_bytes = bytes; m->image_crc32 = I1BootCrc32(image, bytes);
    m->seed = I1_BOOT_SEED; m->iterations = I1_BOOT_ITERATIONS;
    m->state = I1_BOOT_READY;
    Xil_DCacheFlushRange((INTPTR)I1_PS_BOOT_MAILBOX, sizeof(*m));
    __asm__ volatile("dsb sy" ::: "memory");
    XGpioPs_WritePin(gpio, I1_PS_DDR_READY_GPIO, 1U);
    XGpioPs_WritePin(gpio, I1_PS_START_GPIO, 1U);
    __asm__ volatile("dsb sy" ::: "memory");
    return XST_SUCCESS;
}

int I1PsReadSelftest(I1BootMailbox *report)
{
    /* RPU has no dirty mailbox bytes after publication. The RV writes through
     * its cache and publishes terminal state after the other result stores.
     */
    Xil_DCacheInvalidateRange((INTPTR)I1_PS_BOOT_MAILBOX, sizeof(*report));
    __asm__ volatile("dsb sy" ::: "memory");
    volatile const I1BootMailbox *m = (volatile const I1BootMailbox *)(UINTPTR)I1_PS_BOOT_MAILBOX;
    uint32_t state = m->state;
    if (state != I1_BOOT_PASSED && state != I1_BOOT_FAILED) return XST_DEVICE_BUSY;
    __asm__ volatile("dmb sy" ::: "memory");
    uint8_t *target = (uint8_t *)report;
    volatile const uint8_t *source = (volatile const uint8_t *)m;
    for (unsigned i = 0; i < sizeof(*report); ++i) target[i] = source[i];
    if (state == I1_BOOT_FAILED) return XST_FAILURE;
    return report->error == 0 && report->observed_crc32 == report->image_crc32 &&
        report->kernel_checksum == I1BootKernel(report->seed, report->iterations) ? XST_SUCCESS : XST_FAILURE;
}
