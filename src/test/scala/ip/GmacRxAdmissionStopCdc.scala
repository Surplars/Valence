package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.ethernet._

/** CDC-only proof boundary. Native frame ownership and CPU status storage are
  * deliberately small surrogates; no MAC, PHY, CPU, CSR or DMA is instantiated.
  * The independent SV bench owns frame starts, beat contents and status release.
  */
class GmacRxAdmissionStopCdcTop extends RawModule {
    val controlClock = IO(Input(Clock()))
    val rxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val requested = IO(Input(Bool()))
    val frameStart = IO(Input(Bool()))
    val frameStartReady = IO(Output(Bool()))
    val nativeFrameActive = IO(Output(Bool()))
    val rxIn = IO(Flipped(Decoupled(new EthernetFrameBeat(4))))
    val rxOut = IO(Decoupled(new EthernetFrameBeat(4)))
    val statusReady = IO(Input(Bool()))
    val statusValid = IO(Output(Bool()))
    val rxFifoSourceIdle = IO(Output(Bool()))
    val cpuFifoIdle = IO(Output(Bool()))
    val stopNewFrames = IO(Output(Bool()))
    val settled = IO(Output(Bool()))
    val drained = IO(Output(Bool()))

    val rxRelease = Module(new CdcResetRelease)
    rxRelease.clockIn := rxClock
    rxRelease.asyncReset := commonReset
    val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := controlClock
    cpuRelease.asyncReset := commonReset
    val bridge = Module(new EthernetFrameClockBridge(4))
    bridge.sourceClock := rxClock
    bridge.destinationClock := controlClock
    bridge.commonReset := commonReset
    val barrier = Module(new EthernetRxAdmissionStop)
    barrier.sourceClock := controlClock
    barrier.destinationClock := rxClock
    barrier.commonReset := commonReset
    barrier.requested := requested

    // Admission is separate from beat flow: an already owned frame must finish
    // even if a stop offer arrives while its output is backpressured.
    val active = withClockAndReset(rxClock, rxRelease.resetOut) { RegInit(false.B) }
    frameStartReady := !active && !barrier.stopNewFrames && !rxRelease.resetOut.asBool
    withClockAndReset(rxClock, rxRelease.resetOut) {
        when(frameStart && frameStartReady) { active := true.B }
        when(bridge.source.fire && bridge.source.bits.last) { active := false.B }
    }
    bridge.source.valid := rxIn.valid && active
    bridge.source.bits := rxIn.bits
    rxIn.ready := bridge.source.ready && active
    nativeFrameActive := active

    // A one-entry adapter status tail outlives the last data beat. Holding it
    // also prevents overwriting that status with a later frame's completion.
    val statusHeld = withClockAndReset(controlClock, cpuRelease.resetOut) { RegInit(false.B) }
    val canForward = !statusHeld && !cpuRelease.resetOut.asBool
    rxOut.valid := bridge.destination.valid && canForward
    rxOut.bits := bridge.destination.bits
    bridge.destination.ready := rxOut.ready && canForward
    statusValid := statusHeld && !cpuRelease.resetOut.asBool
    withClockAndReset(controlClock, cpuRelease.resetOut) {
        when(statusValid && statusReady) { statusHeld := false.B }
        when(rxOut.fire && rxOut.bits.last) { statusHeld := true.B }
    }
    barrier.destinationFrameIdle := !active
    barrier.destinationFifoIdle := bridge.sourceIdle
    barrier.sourceDrained := bridge.destinationIdle && !statusHeld
    rxFifoSourceIdle := bridge.sourceIdle
    cpuFifoIdle := bridge.destinationIdle
    stopNewFrames := barrier.stopNewFrames
    settled := barrier.settled
    drained := barrier.drained
}

object GmacRxAdmissionStopCdcMain extends App {
    require(args.length == 1, "usage: GmacRxAdmissionStopCdcMain <fresh-rtl-directory>")
    ChiselStage.emitSystemVerilogFile(new GmacRxAdmissionStopCdcTop, Array("--target-dir", args.head),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
}
