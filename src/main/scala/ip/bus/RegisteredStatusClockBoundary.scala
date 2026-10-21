package soc.ip.bus

import chisel3._

/** Opt-in persistent status crossing with a registered source and local reset release.
  *
  * statusIn must be synchronous to sourceClock, not a pulse. This helper does not
  * detect failures while sourceClock is stopped. A fault which must revoke status
  * without either clock (for example DDR calibration loss) MUST asynchronously
  * assert commonColdReset for both endpoints. The board's calibration/reset
  * request already supplies that contract. Deassertion is local and synchronous;
  * a stopped endpoint therefore cannot reuse a pre-reset true status on restart.
  * A status change without commonColdReset propagates only with running clocks.
  *
  * This module is not instantiated by default. Its source-to-first-stage path
  * still requires scoped physical CDC constraints and implementation review.
  */
class RegisteredStatusClockBoundary extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val statusIn = IO(Input(Bool()))
    val statusOut = IO(Output(Bool()))

    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonColdReset
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonColdReset

    val registeredStatus = withClockAndReset(sourceClock, sourceRelease.resetOut) {
        RegNext(statusIn, false.B)
    }
    val statusSync = Module(new CdcLevel)
    statusSync.clockIn := destinationClock
    statusSync.resetIn := destinationRelease.resetOut
    statusSync.levelIn := registeredStatus
    statusOut := statusSync.levelOut
}
