#ifndef I1_PS_LOADER_H
#define I1_PS_LOADER_H
#include "xgpiops.h"
#include "i1_boot_protocol.h"

/* Board BD contract: PS EMIO 0/1 -> start/ddrReady, EMIO 2 <- started.
 * RV 0x80000000..0x8fffffff aliases PS DDR 0x40000000..0x4fffffff.
 * Keep this entire DDR window out of the RPU linker and lwIP buffer pools.
 */
#define I1_PS_START_GPIO 78U
#define I1_PS_DDR_READY_GPIO 79U
#define I1_PS_STARTED_GPIO 80U

/* GPIO and PS DDR must already be initialized by the board BSP/FSBL.
 * image is a flat RV binary linked at 0x80000000, staged outside the RV window.
 * The caller owns this cold launch; no concurrent calls or live image reloads.
 * Success means release was requested; poll GPIO 80 to observe started.
 */
/* Claim the cold DDR window before destructive DDR testing. */
int I1PsHoldForColdLaunch(XGpioPs *gpio);
int I1PsLoadAndStart(XGpioPs *gpio, const void *image, u32 bytes);
/* Poll once. Returns XST_DEVICE_BUSY until terminal status; no infinite wait.
 * The cold-boot selftest owns output lines after start, so invalidation is safe.
 */
int I1PsReadSelftest(I1BootMailbox *report);
#endif
