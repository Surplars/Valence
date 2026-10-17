package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.ip.bus._
import soc.ip.clock._

// Unchanged shared gate/retention test composition; no OoO implementation dependency.
class ManagedClockCdcTop(balanced: Boolean = false) extends RawModule {
    val alwaysOnClock = IO(Input(Clock()))
    val rawClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val stop = IO(Input(Bool()))
    val wake = IO(Input(Bool()))
    val idle = IO(Input(Bool()))
    val clearFault = IO(Input(Bool()))
    val managedClock = IO(Output(Clock()))
    val retainedClock = IO(Output(Clock()))
    val mailboxIn = IO(Flipped(Decoupled(UInt(64.W))))
    val mailboxOut = IO(Decoupled(UInt(64.W)))
    val enabled = IO(Output(Bool()))
    val quiesce = IO(Output(Bool()))
    val isolate = IO(Output(Bool()))
    val admission = IO(Output(Bool()))
    val stopped = IO(Output(Bool()))
    val fault = IO(Output(Bool()))
    val domainAck = IO(Output(Bool()))
    val release = Module(new CdcResetRelease)
    release.clockIn := alwaysOnClock
    release.asyncReset := commonReset
    val policy = withClockAndReset(alwaysOnClock, release.resetOut) {
        Module(new PeripheralClockControl(32, 3))
    }
    policy.io.stopRequest := stop
    policy.io.wake := wake
    policy.io.clearFault := clearFault
    val running = if (balanced) {
        val keepRunning = Module(new ContinuousClockBuffer)
        keepRunning.rawClock := rawClock
        keepRunning.runningClock
    } else rawClock
    retainedClock := running
    val mailbox = Module(new CdcMailbox(64))
    mailbox.sourceClock := running
    mailbox.destinationClock := alwaysOnClock
    mailbox.commonReset := commonReset
    mailbox.source <> mailboxIn
    mailboxOut <> mailbox.destination
    val gate = Module(new ManagedClockBuffer(independentControlClock = balanced))
    gate.rawClock := rawClock
    gate.controlClock.foreach(_ := running)
    gate.commonReset := commonReset
    gate.enable := policy.io.clockEnable
    managedClock := gate.managedClock
    val agent = Module(new PeripheralQuiesceAck)
    agent.domainClock := gate.managedClock
    agent.commonReset := commonReset
    agent.quiesce := policy.io.quiesce
    agent.idle := idle
    policy.io.domainAck := agent.ack
    domainAck := agent.ack
    enabled := policy.io.clockEnable
    quiesce := policy.io.quiesce
    isolate := policy.io.isolate
    admission := policy.io.allowAdmission
    stopped := policy.io.stopped
    fault := policy.io.fault
}

object I1ManagedClockCdcRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new ManagedClockCdcTop(args.contains("--balanced")),
        Array("--target-dir", args.head),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
}
