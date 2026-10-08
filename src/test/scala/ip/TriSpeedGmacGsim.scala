package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.ethernet._

/** Single-clock functional test boundary. The RX clock frequency is external
  * to the nibble decoder; this model does not claim independent-clock CDC proof.
  */
class TriSpeedFramesGsim(frameSlots: Int = 4, txFrameSlots: Int = 1) extends Module {
    val io = IO(new Bundle {
        val txFrame = Flipped(Decoupled(new EthernetFrameBeat(4)))
        val rxFrame = Decoupled(new EthernetFrameBeat(4))
        val txRate = Flipped(Decoupled(UInt(2.W)))
        val rxRate = Flipped(Decoupled(UInt(2.W)))
        val txAbort = Input(Bool())
        val rxAbort = Input(Bool())
        val rxStop = Input(Bool())
        val rxRise = Input(UInt(5.W))
        val rxFall = Input(UInt(5.W))
        val txRise = Output(UInt(5.W))
        val txFall = Output(UInt(5.W))
        val txClockRise = Output(Bool())
        val txClockFall = Output(Bool())
        val txByteStep = Output(Bool())
        val txInputAccepted = Output(Bool())
        val txInputLast = Output(Bool())
        val txInputOverlap = Output(Bool())
        val txInputStalled = Output(Bool())
        val txAppliedSpeed = Output(UInt(2.W))
        val rxAppliedSpeed = Output(UInt(2.W))
        val txBusy = Output(Bool())
        val rxBusy = Output(Bool())
        val txDone = Output(Bool())
        val txRejected = Output(Bool())
        val txAborted = Output(Bool())
        val rxAccepted = Output(Bool())
        val rxDropped = Output(Bool())
        val rxBadFcs = Output(Bool())
        val rxDropReasons = Output(UInt(8.W))
        val rxOddNibble = Output(Bool())
        val rxByteStep = Output(Bool())
        val rxGmiiData = Output(UInt(8.W))
        val rxGmiiValid = Output(Bool())
        val rxGmiiError = Output(Bool())
    })
    val tx: EthernetFrameTransmitter = if (txFrameSlots == 1) Module(new GmiiFrameTx(rateAdaptation = true))
        else Module(new QueuedGmiiFrameTx(frameSlots = txFrameSlots))
    val rx = Module(new GmiiFrameRx(admissionStop = true, frameSlots = frameSlots,
        rateAdaptation = true, diagnostics = true))
    val encode = Module(new TriSpeedRgmiiTx)
    val decode = Module(new TriSpeedRgmiiRx)
    tx.io.frame <> io.txFrame
    io.txInputAccepted := tx.io.frame.fire
    io.txInputLast := tx.io.frame.fire && tx.io.frame.bits.last
    io.txInputOverlap := tx.io.frame.fire && tx.io.gmiiEnable
    io.txInputStalled := tx.io.frame.valid && !tx.io.frame.ready
    io.rxFrame <> rx.io.frame
    tx.io.enable := true.B
    tx.io.byteStep.get := encode.io.byteStep
    tx.io.abort.get := io.txAbort
    encode.io.rate <> io.txRate
    encode.io.datapathIdle := !tx.io.busy
    encode.io.gmiiData := tx.io.gmiiData
    encode.io.gmiiEnable := tx.io.gmiiEnable
    encode.io.gmiiError := tx.io.gmiiError
    io.txRise := encode.io.rise
    io.txFall := encode.io.fall
    io.txClockRise := encode.io.clockRise
    io.txClockFall := encode.io.clockFall
    io.txByteStep := encode.io.byteStep
    io.txAppliedSpeed := encode.io.appliedSpeed
    io.rxAppliedSpeed := decode.io.appliedSpeed
    decode.io.rate <> io.rxRate
    decode.io.admissionClosed := io.rxStop
    decode.io.abort := io.rxAbort
    decode.io.rise := io.rxRise
    decode.io.fall := io.rxFall
    rx.io.byteStep.get := decode.io.byteStep
    rx.io.abort.get := io.rxAbort
    rx.io.gmiiData := decode.io.gmiiData
    rx.io.gmiiValid := decode.io.gmiiValid
    rx.io.gmiiError := decode.io.gmiiError
    rx.io.enable := !io.rxAbort
    rx.io.stopNewFrames.get := io.rxStop
    rx.io.macAddress := "h021122334455".U
    rx.io.promiscuous := false.B
    rx.io.broadcastEnable := true.B
    io.txBusy := tx.io.busy
    io.rxBusy := rx.io.busy
    io.txDone := tx.io.done
    io.txRejected := tx.io.rejected
    io.txAborted := tx.io.aborted.get
    io.rxAccepted := rx.io.accepted
    io.rxDropped := rx.io.dropped
    io.rxBadFcs := rx.io.badFcs
    io.rxDropReasons := rx.io.dropReasons.get
    io.rxOddNibble := decode.io.oddNibble
    io.rxByteStep := decode.io.byteStep
    io.rxGmiiData := decode.io.gmiiData
    io.rxGmiiValid := decode.io.gmiiValid
    io.rxGmiiError := decode.io.gmiiError
}

object TriSpeedFramesGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TriSpeedFramesGsim(args.lift(1).map(_.toInt).getOrElse(4), args.lift(2).map(_.toInt).getOrElse(1)),
        Array("--target-dir", args.head))
}

object TriSpeedFramesRtlMain extends App {
    val options = Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info")
    ChiselStage.emitSystemVerilogFile(new TriSpeedFramesGsim,
        Array("--target-dir", args.head + "/frames"), options)
    ChiselStage.emitSystemVerilogFile(new TriSpeedRgmiiTx,
        Array("--target-dir", args.head + "/tx-codec"), options)
    ChiselStage.emitSystemVerilogFile(new TriSpeedRgmiiRx,
        Array("--target-dir", args.head + "/rx-codec"), options)
}

object Rtl8211fPhyManagerGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new Rtl8211fPhyManager(startupCycles = 4, pollCycles = 19),
        Array("--target-dir", args.head))
}
object EthernetMediaTransitionGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetMediaTransition(64), Array("--target-dir", args.head))
}
object ManagedMdioArbiterGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new ManagedMdioArbiter, Array("--target-dir", args.head))
}
object TriSpeedManagedGmacRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new TriSpeedManagedGmac(hardwareClocks = args.lift(1).contains("hardware"),
        txFrameSlots = args.lift(2).map(_.toInt).getOrElse(1)),
        Array("--target-dir", args.head),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
}

/** Functional pack/unpack proof with a deliberately tiny, backpressured token
  * channel. Independent clocks/reset assertion require the native CDC bench.
  */
class EthernetIngressGsim extends Module {
    val io = IO(new Bundle {
        val data = Input(UInt(8.W))
        val valid = Input(Bool())
        val error = Input(Bool())
        val byteStep = Input(Bool())
        val captureEnable = Input(Bool())
        val stall = Input(Bool())
        val epochReset = Input(Bool())
        val outData = Output(UInt(8.W))
        val outValid = Output(Bool())
        val outError = Output(Bool())
        val outStep = Output(Bool())
        val overflow = Output(Bool())
        val skipped = Output(Bool())
        val idle = Output(Bool())
        val frame = Decoupled(new EthernetFrameBeat(4))
        val accepted = Output(Bool())
        val dropped = Output(Bool())
        val dropReasons = Output(UInt(8.W))
    })
    val localReset = reset.asBool || io.epochReset
    val pack = withReset(localReset) { Module(new EthernetIngressPacker) }
    val unpack = withReset(localReset) { Module(new EthernetIngressUnpacker) }
    val queue = withReset(localReset) { Module(new Queue(new EthernetFrameBeat(4), 4, pipe = false, flow = false)) }
    pack.io.data := io.data
    pack.io.valid := io.valid
    pack.io.error := io.error
    pack.io.byteStep := io.byteStep
    pack.io.physicalValid := io.valid
    pack.io.captureEnable := io.captureEnable
    queue.io.enq <> pack.io.word
    unpack.io.word.valid := queue.io.deq.valid && !io.stall
    unpack.io.word.bits := queue.io.deq.bits
    queue.io.deq.ready := unpack.io.word.ready && !io.stall
    io.outData := unpack.io.data
    io.outValid := unpack.io.valid
    io.outError := unpack.io.error
    io.outStep := unpack.io.byteStep
    io.overflow := pack.io.overflow
    io.skipped := pack.io.wholeFrameSkipped
    io.idle := unpack.io.idle && !queue.io.deq.valid && !pack.io.word.valid
    val rx = Module(new GmiiFrameRx(admissionStop = true, rateAdaptation = true, diagnostics = true))
    rx.io.gmiiData := unpack.io.data
    rx.io.gmiiValid := unpack.io.valid
    rx.io.gmiiError := unpack.io.error
    rx.io.byteStep.get := unpack.io.byteStep
    rx.io.abort.get := io.epochReset
    rx.io.enable := io.captureEnable
    rx.io.stopNewFrames.get := !io.captureEnable
    rx.io.macAddress := "h021122334455".U
    rx.io.promiscuous := false.B
    rx.io.broadcastEnable := true.B
    io.frame <> rx.io.frame
    io.accepted := rx.io.accepted
    io.dropped := rx.io.dropped
    io.dropReasons := rx.io.dropReasons.get
}
object EthernetIngressGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetIngressGsim, Array("--target-dir", args.head))
}
object EthernetPhysicalIngressRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new EthernetPhysicalIngress,
        Array("--target-dir", args.head),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
}

class TriSpeedControlGsim extends Module {
    val io = IO(new Bundle {
        val registers = Flipped(new soc.ip.bus.RegisterPort)
        val mediaStatus = Input(UInt(64.W))
        val phyErrors = Input(UInt(64.W))
        val phyPolls = Input(UInt(64.W))
        val phyTransitions = Input(UInt(64.W))
        val diagnosticIndex = Input(UInt(4.W))
        val diagnosticIncrement = Input(UInt(32.W))
        val totalIndex = Input(UInt(3.W))
        val totalIncrement = Input(UInt(32.W))
        val linkUp = Input(Bool())
        val txBusy = Input(Bool())
        val rxBusy = Input(Bool())
        val rxDrained = Input(Bool())
        val events = Input(UInt(6.W))
        val mdioCommand = Decoupled(new MdioCommand)
        val mdioResponse = Flipped(Decoupled(new MdioResponse))
        val restartPhy = Output(Bool())
        val irq = Output(Bool())
    })
    val config = GmacParams(aggregateStats = true, rxAdmissionStop = true, rxFrameSlots = 4,
        triSpeedExtensions = true, externalMdio = true)
    val params = soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)
    val frontend = Module(new RegisterGmacControl(config.base, params))
    val csr = Module(new TileLinkGmacControl(config, params))
    frontend.io.registers <> io.registers
    csr.io.tl <> frontend.io.tl
    val port = csr.io.ports.head
    port.linkUp := io.linkUp
    port.txBusy := io.txBusy
    port.rxBusy := io.rxBusy
    port.rxStopDrained.get := io.rxDrained
    port.events := io.events
    port.txBytes := 0.U
    port.rxBytes := 0.U
    port.mdioIn := true.B
    port.mediaStatus.get := io.mediaStatus
    port.phyCounters.get := VecInit(Seq(io.phyErrors, io.phyPolls, io.phyTransitions))
    for (n <- 0 until 6) port.deltas.get(n) := Mux(io.totalIndex === n.U, io.totalIncrement, 0.U)
    for (n <- 0 until 14) port.diagnosticDeltas.get(n) := Mux(io.diagnosticIndex === n.U, io.diagnosticIncrement, 0.U)
    io.mdioCommand <> port.mdioCommand.get
    port.mdioResponse.get <> io.mdioResponse
    io.restartPhy := port.restartPhy.get
    io.irq := csr.io.irq.orR
}
object TriSpeedControlGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TriSpeedControlGsim, Array("--target-dir", args.head))
}
object TriSpeedMdioClause22GsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MdioClause22(clockHz = 100000000, mdcHz = 1250000),
        Array("--target-dir", args.head))
}
