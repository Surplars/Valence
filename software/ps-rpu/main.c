#include "i1_ps_loader.h"
#ifndef I1_RPU_DDR_ONLY
#include "i1_embedded_rv_image.h"
#endif
#include "xil_cache.h"
#include "xparameters.h"
#include "xstatus.h"
#include "xiltimer.h"

/* Read this symbol with JTAG even when no PS UART is connected. All RPU code,
 * stack and this report must remain outside the reserved PS DDR RV window.
 */
struct I1RpuReport {
    uint32_t phase, status, bad_address, expected, observed;
    I1BootMailbox rv;
};
volatile struct I1RpuReport g_i1_rpu_report;
#ifndef I1_RPU_DDR_ONLY
static XGpioPs gpio;
#endif

static int check_word(uint32_t address, uint32_t expected)
{
    uint32_t observed = *(volatile uint32_t *)(UINTPTR)address;
    if (observed == expected) return XST_SUCCESS;
    g_i1_rpu_report.bad_address = address;
    g_i1_rpu_report.expected = expected;
    g_i1_rpu_report.observed = observed;
    return XST_FAILURE;
}

static int check_ddr(void)
{
    const uint32_t bytes = 65536U;
    for (unsigned pass = 0; pass < 2; ++pass) {
        uint32_t pattern = pass ? 0x55555555U : 0xaaaaaaaaU;
        for (uint32_t offset = 0; offset < bytes; offset += 4U)
            *(volatile uint32_t *)(UINTPTR)(I1_PS_DDR_BASE + offset) = pattern ^ offset;
        Xil_DCacheFlushRange(I1_PS_DDR_BASE, bytes);
        Xil_DCacheInvalidateRange(I1_PS_DDR_BASE, bytes);
        for (uint32_t offset = 0; offset < bytes; offset += 4U)
            if (check_word(I1_PS_DDR_BASE + offset, pattern ^ offset) != XST_SUCCESS)
                return XST_FAILURE;
    }
    /* Address-line samples cover the 256 MiB shared window before image load.
     * This is a short handoff-window test, not a claim of testing all 4 GiB.
     */
    for (uint32_t offset = 64U; offset < I1_PS_DDR_BYTES; offset <<= 1) {
        *(volatile uint32_t *)(UINTPTR)(I1_PS_DDR_BASE + offset) = 0x13579bdfU ^ offset;
        Xil_DCacheFlushRange(I1_PS_DDR_BASE + offset, 64U);
    }
    for (uint32_t offset = 64U; offset < I1_PS_DDR_BYTES; offset <<= 1) {
        Xil_DCacheInvalidateRange(I1_PS_DDR_BASE + offset, 64U);
        if (check_word(I1_PS_DDR_BASE + offset, 0x13579bdfU ^ offset) != XST_SUCCESS)
            return XST_FAILURE;
    }
    return XST_SUCCESS;
}

int main(void)
{
    g_i1_rpu_report.phase = 1;
    int status;
    #ifndef I1_RPU_DDR_ONLY
    XGpioPs_Config *config = XGpioPs_LookupConfig(XPAR_XGPIOPS_0_BASEADDR);
    status = XGpioPs_CfgInitialize(&gpio, config, config->BaseAddr);
    if (status == XST_SUCCESS) status = I1PsHoldForColdLaunch(&gpio);
    if (status != XST_SUCCESS) goto failed;
    #endif
    /* The DDR-only JTAG script performs a cold system reset. It must work
     * before PL is configured, when EMIO started has no valid producer.
     */
    g_i1_rpu_report.phase = 2;
    status = check_ddr();
    if (status != XST_SUCCESS) goto failed;
    #ifndef I1_RPU_DDR_ONLY
    g_i1_rpu_report.phase = 3;
    status = I1PsLoadAndStart(&gpio, i1_rv_image, I1_RV_IMAGE_BYTES);
    if (status != XST_SUCCESS) goto failed;
    #ifdef I1_RPU_LOAD_ONLY
    /* This acknowledges image publication and release only. OpenSBI/Linux
     * completion is observed separately through UART or their own probe.
     */
    g_i1_rpu_report.phase = 7;
    #else
    g_i1_rpu_report.phase = 4;
    XTime begin, now;
    XTime_GetTime(&begin);
    I1BootMailbox report;
    do {
        status = I1PsReadSelftest(&report);
        XTime_GetTime(&now);
    } while (status == XST_DEVICE_BUSY && (XTime)(now - begin) < 10U * COUNTS_PER_SECOND);
    if (status != XST_DEVICE_BUSY) g_i1_rpu_report.rv = report;
    if (status != XST_SUCCESS) goto failed;
    g_i1_rpu_report.phase = 5;
    #endif
    #else
    g_i1_rpu_report.phase = 6;
    #endif
    g_i1_rpu_report.status = XST_SUCCESS;
    Xil_DCacheFlushRange((INTPTR)&g_i1_rpu_report, sizeof(g_i1_rpu_report));
    for (;;) __asm__ volatile("wfi");
failed:
    g_i1_rpu_report.status = (uint32_t)status;
    g_i1_rpu_report.phase |= 0x80000000U;
    Xil_DCacheFlushRange((INTPTR)&g_i1_rpu_report, sizeof(g_i1_rpu_report));
    for (;;) __asm__ volatile("wfi");
}
