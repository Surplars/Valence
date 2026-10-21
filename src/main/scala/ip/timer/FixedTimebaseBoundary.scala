package soc.ip.timer

import chisel3._
import soc.ip.bus.{CdcLevel, CdcMailbox, RegisterClockDomainBridge, RegisterPort}

/** Fixed-frequency timer outside the variable fabric domain. No tick pulses cross:
  * the complete MMIO transaction crosses to mtime/mtimecmp, while read-time uses
  * coherent, possibly stale, 64-bit snapshots. Common cold reset only. Bundled
  * mailbox payloads require physical max-delay constraints and CDC review.
  */
class FixedTimebaseBoundary extends RawModule {
    val fabricClock = IO(Input(Clock()))
    val timebaseClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val irq = IO(Output(Bool()))
    val timeSnapshot = IO(Output(UInt(64.W)))
    val mmio = Module(new RegisterClockDomainBridge)
    mmio.sourceClock := fabricClock
    mmio.destinationClock := timebaseClock
    mmio.commonReset := commonColdReset
    mmio.source <> registers
    val timer = withClockAndReset(timebaseClock, mmio.destinationReset) { Module(new MachineTimer()) }
    timer.io.mmio <> mmio.destination
    timer.io.tick := true.B
    val interrupt = Module(new CdcLevel)
    interrupt.clockIn := fabricClock
    interrupt.resetIn := mmio.sourceReset
    interrupt.levelIn := timer.io.irq
    irq := interrupt.levelOut
    val snapshots = Module(new CdcMailbox(64))
    snapshots.sourceClock := timebaseClock
    snapshots.destinationClock := fabricClock
    snapshots.commonReset := commonColdReset
    snapshots.source.valid := true.B
    snapshots.source.bits := timer.io.timeValue
    snapshots.destination.ready := true.B
    timeSnapshot := withClockAndReset(fabricClock, mmio.sourceReset) {
        val held = RegInit(0.U(64.W))
        when(snapshots.destination.fire) { held := snapshots.destination.bits }
        held
    }
}
