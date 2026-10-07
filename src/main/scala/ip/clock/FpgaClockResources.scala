package soc.ip.clock

import chisel3._
import chisel3.util._
import chisel3.experimental.StringParam
import soc.ip.bus._

private class GlitchlessClockBuffer extends BlackBox(Map("CE_TYPE" -> StringParam("SYNC"))) {
    override def desiredName = "BUFGCE"
    val io = IO(new Bundle {
        val I = Input(Clock())
        val CE = Input(Bool())
        val O = Output(Clock())
    })
}

/** FPGA backend, not clk&CE. Command is synchronized on the UNGATED source
  * clock, which must keep oscillating while its managed output is stopped.
  * This never resets MMCM/MIG or changes their rate. Common cold reset only.
  */
class ManagedClockBuffer extends RawModule {
    val rawClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val enable = IO(Input(Bool()))
    val managedClock = IO(Output(Clock()))
    val release = Module(new CdcResetRelease)
    release.clockIn := rawClock
    release.asyncReset := commonReset
    val command = Module(new CdcLevel)
    command.clockIn := rawClock
    command.resetIn := release.resetOut
    command.levelIn := enable
    private val buffer = Module(new GlitchlessClockBuffer)
    buffer.io.I := rawClock
    buffer.io.CE := command.levelOut
    managedClock := buffer.io.O
}

/** Complete standalone CMU/backend resource bank, still outside a CPU.
  * Registers are in alwaysOnClock; every controllable endpoint supplies its
  * true LOCAL idle and persistent wake. No software access proxy is implied:
  * callers must reject/wake stalled peripheral accesses while isolated.
  */
class FpgaClockResources(config: CmuParams) extends RawModule {
    val alwaysOnClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val rawClocks = IO(Input(Vec(config.resources.size, Clock())))
    val clocks = IO(Output(Vec(config.resources.size, Clock())))
    val localIdle = IO(Input(Vec(config.resources.size, Bool())))
    val wake = IO(Input(Vec(config.resources.size, Bool())))
    val stopAdmission = IO(Output(Vec(config.resources.size, Bool())))
    val isolate = IO(Output(Vec(config.resources.size, Bool())))
    val irq = IO(Output(Bool()))
    val release = Module(new CdcResetRelease)
    release.clockIn := alwaysOnClock
    release.asyncReset := commonReset
    val cmu = withClockAndReset(alwaysOnClock, release.resetOut) { Module(new ClockManagementUnit(config)) }
    cmu.io.registers <> registers
    irq := cmu.io.irq
    for ((resource, n) <- config.resources.zipWithIndex) {
        if (resource.canGate) {
            val gate = Module(new ManagedClockBuffer)
            gate.rawClock := rawClocks(n)
            gate.commonReset := commonReset
            gate.enable := cmu.io.resources(n).clockEnable
            clocks(n) := gate.managedClock
            val agent = Module(new PeripheralQuiesceAck)
            agent.domainClock := gate.managedClock
            agent.commonReset := commonReset
            agent.quiesce := cmu.io.resources(n).quiesce
            agent.idle := localIdle(n)
            cmu.io.resources(n).ack := agent.ack
            stopAdmission(n) := agent.stopAdmission
        } else {
            clocks(n) := (if (n == 0) alwaysOnClock else rawClocks(n))
            cmu.io.resources(n).ack := false.B
            stopAdmission(n) := false.B
        }
        cmu.io.resources(n).wake := wake(n)
        isolate(n) := cmu.io.resources(n).isolate
    }
}
