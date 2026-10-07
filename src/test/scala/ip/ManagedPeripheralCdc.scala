package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.clock._

/** CDC-only surrogate sink: no UART, MAC, CPU or DMA behavior in xsim.
  * The delay, register admission/bridge, counter image, policy, ACK and actual
  * BUFGCE are EXACT production primitives. Raw sources are never gated.
  */
class ManagedIngressCdcLane(cycles: Int) extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val rawClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val stop = IO(Input(Bool()))
    val rawData = IO(Input(UInt(8.W)))
    val rawValid = IO(Input(Bool()))
    val statsReady = IO(Input(Bool()))
    val registers = IO(Flipped(new RegisterPort))
    val managedClock = IO(Output(Clock()))
    val stopped = IO(Output(Bool()))
    val fault = IO(Output(Bool()))
    val capturedData = IO(Output(UInt(8.W)))
    val capturedValid = IO(Output(Bool()))
    val statValid = IO(Output(Bool()))
    val statCount = IO(Output(UInt(32.W)))
    val statSum = IO(Output(UInt(32.W)))
    val aonRelease = Module(new CdcResetRelease)
    aonRelease.clockIn := alwaysOnClock
    aonRelease.asyncReset := commonReset
    val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := sourceClock
    cpuRelease.asyncReset := commonReset
    val policy = withClockAndReset(alwaysOnClock, aonRelease.resetOut) {
        Module(new PeripheralClockControl(2048))
    }
    policy.io.stopRequest := stop
    policy.io.clearFault := false.B
    stopped := policy.io.stopped
    fault := policy.io.fault
    val gate = Module(new ManagedClockBuffer)
    gate.rawClock := rawClock
    gate.commonReset := commonReset
    gate.enable := policy.io.clockEnable
    managedClock := gate.managedClock
    val delay = Module(new PeripheralWakeDelay(9, cycles))
    delay.rawClock := rawClock
    delay.commonReset := commonReset
    delay.payload := Cat(rawValid, rawData)
    delay.active := rawValid
    delay.quiesce := policy.io.quiesce
    delay.isolate := policy.io.isolate
    capturedData := delay.delayed(7, 0)
    capturedValid := delay.delayed(8)
    val bridge = Module(new RegisterClockDomainBridge)
    bridge.sourceClock := sourceClock
    bridge.destinationClock := gate.managedClock
    bridge.commonReset := commonReset
    val proxy = withClockAndReset(sourceClock, cpuRelease.resetOut) { Module(new ClockRegisterAdmission) }
    proxy.io.upstream <> registers
    bridge.source <> proxy.io.downstream
    proxy.io.downstreamIdle := bridge.sourceIdle
    proxy.io.quiesce := ManagedPeripheralSupport.level(policy.io.quiesce, sourceClock, cpuRelease.resetOut)
    proxy.io.isolate := ManagedPeripheralSupport.level(policy.io.isolate, sourceClock, cpuRelease.resetOut)
    val receiverWake = ManagedPeripheralSupport.level(delay.wake, sourceClock, cpuRelease.resetOut)
    val mergedWake = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        RegNext(proxy.io.wake || receiverWake, false.B)
    }
    policy.io.wake := ManagedPeripheralSupport.level(mergedWake, alwaysOnClock, aonRelease.resetOut)
    val replyPending = withClockAndReset(gate.managedClock, bridge.destinationReset) {
        val pending = RegInit(false.B)
        val scratch = RegInit(0.U(64.W))
        val reply = RegInit(0.U(64.W))
        bridge.destination.request.ready := !pending
        bridge.destination.response.valid := pending
        bridge.destination.response.bits.data := reply
        bridge.destination.response.bits.error := false.B
        when(bridge.destination.request.fire) {
            when(bridge.destination.request.bits.write) { scratch := bridge.destination.request.bits.data }
            reply := scratch
            pending := true.B
        }
        when(bridge.destination.response.fire) { pending := false.B }
        pending
    }
    val stats = Module(new CdcCounterBank(2))
    stats.sourceClock := gate.managedClock
    stats.destinationClock := sourceClock
    stats.commonReset := commonReset
    stats.increment(0) := capturedValid.asUInt
    stats.increment(1) := Mux(capturedValid, capturedData, 0.U)
    stats.delta.ready := statsReady
    statValid := stats.delta.valid
    statCount := stats.delta.bits(0)
    statSum := stats.delta.bits(1)
    val sourceDrained = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        RegNext(proxy.io.drained && stats.destinationIdle, false.B)
    }
    val drained = ManagedPeripheralSupport.level(sourceDrained, gate.managedClock, bridge.destinationReset)
    val agent = Module(new PeripheralQuiesceAck)
    agent.domainClock := gate.managedClock
    agent.commonReset := commonReset
    agent.quiesce := policy.io.quiesce
    agent.idle := drained && bridge.destinationIdle && !replyPending && stats.sourceIdle && delay.empty
    policy.io.domainAck := agent.ack
}

class ManagedPeripheralCdcTop extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val slowClock = IO(Input(Clock()))
    val fastClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    class Signals extends Bundle {
        val stop = Input(Bool())
        val rawData = Input(UInt(8.W))
        val rawValid = Input(Bool())
        val statsReady = Input(Bool())
        val registers = Flipped(new RegisterPort)
        val managedClock = Output(Clock())
        val stopped = Output(Bool())
        val fault = Output(Bool())
        val capturedData = Output(UInt(8.W))
        val capturedValid = Output(Bool())
        val statValid = Output(Bool())
        val statCount = Output(UInt(32.W))
        val statSum = Output(UInt(32.W))
    }
    val slow = IO(new Signals)
    val fast = IO(new Signals)
    for ((signals, raw, cycles) <- Seq((slow, slowClock, 64), (fast, fastClock, 128))) {
        val lane = Module(new ManagedIngressCdcLane(cycles))
        lane.sourceClock := sourceClock
        lane.alwaysOnClock := alwaysOnClock
        lane.rawClock := raw
        lane.commonReset := commonReset
        lane.stop := signals.stop
        lane.rawData := signals.rawData
        lane.rawValid := signals.rawValid
        lane.statsReady := signals.statsReady
        lane.registers <> signals.registers
        signals.managedClock := lane.managedClock
        signals.stopped := lane.stopped
        signals.fault := lane.fault
        signals.capturedData := lane.capturedData
        signals.capturedValid := lane.capturedValid
        signals.statValid := lane.statValid
        signals.statCount := lane.statCount
        signals.statSum := lane.statSum
    }
}

object ManagedPeripheralCdcRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new ManagedPeripheralCdcTop, Array("--target-dir", args.head),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
}
