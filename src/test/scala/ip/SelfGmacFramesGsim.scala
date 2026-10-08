package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.ethernet._
import soc.ip.bus.RegisterPort
import soc.ip.dma.EthernetPacketDma

/** Single-clock functional wrapper only, never a physical multi-clock MAC top. */
class SelfGmacFramesGsim(frameSlots: Int = 4) extends Module {
    val io = IO(new Bundle {
        val txFrame = Flipped(Decoupled(new EthernetFrameBeat(4)))
        val rxFrame = Decoupled(new EthernetFrameBeat(4))
        val txEnable = Input(Bool())
        val rxEnable = Input(Bool())
        val promiscuous = Input(Bool())
        val broadcastEnable = Input(Bool())
        val macAddress = Input(UInt(48.W))
        val gmiiTxData = Output(UInt(8.W))
        val gmiiTxEnable = Output(Bool())
        val gmiiTxError = Output(Bool())
        val gmiiRxData = Input(UInt(8.W))
        val gmiiRxValid = Input(Bool())
        val gmiiRxError = Input(Bool())
        val txBusy = Output(Bool())
        val rxBusy = Output(Bool())
        val txDone = Output(Bool())
        val txRejected = Output(Bool())
        val rxAccepted = Output(Bool())
        val rxDropped = Output(Bool())
        val rxBadFcs = Output(Bool())
        val txBytes = Output(UInt(16.W))
        val rxBytes = Output(UInt(16.W))
    })
    val tx = Module(new GmiiFrameTx())
    val rx = Module(new GmiiFrameRx(frameSlots = frameSlots))
    tx.io.frame <> io.txFrame
    io.rxFrame <> rx.io.frame
    tx.io.enable := io.txEnable
    rx.io.enable := io.rxEnable
    rx.io.promiscuous := io.promiscuous
    rx.io.broadcastEnable := io.broadcastEnable
    rx.io.macAddress := io.macAddress
    rx.io.gmiiData := io.gmiiRxData
    rx.io.gmiiValid := io.gmiiRxValid
    rx.io.gmiiError := io.gmiiRxError
    io.gmiiTxData := tx.io.gmiiData
    io.gmiiTxEnable := tx.io.gmiiEnable
    io.gmiiTxError := tx.io.gmiiError
    io.txBusy := tx.io.busy
    io.rxBusy := rx.io.busy
    io.txDone := tx.io.done
    io.txRejected := tx.io.rejected
    io.rxAccepted := rx.io.accepted
    io.rxDropped := rx.io.dropped
    io.rxBadFcs := rx.io.badFcs
    io.txBytes := tx.io.bytes
    io.rxBytes := rx.io.bytes
}

/** Real production DMA + native adapter + GMII framing, external memory oracle.
  * All five modules share a test clock; no CPU, CSR, PHY or CDC verification.
  */
class SelfGmacDmaGsim(postedTxSlots: Int = 0, macTxSlots: Int = 1) extends Module {
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val memory = new RegisterPort
        val gmiiTxData = Output(UInt(8.W))
        val gmiiTxEnable = Output(Bool())
        val gmiiTxError = Output(Bool())
        val gmiiRxData = Input(UInt(8.W))
        val gmiiRxValid = Input(Bool())
        val gmiiRxError = Input(Bool())
        val irq = Output(Bool())
        val active = Output(Bool())
        val txBusy = Output(Bool())
        val txDone = Output(Bool())
        val txDmaOverlap = Output(Bool())
        val memoryReadOverlap = Output(Bool())
        val txRejected = Output(Bool())
        val rxAccepted = Output(Bool())
        val rxDropped = Output(Bool())
    })
    val dma = Module(new EthernetPacketDma(ramBytes = 8192, postedTxSlots = postedTxSlots))
    val adapter = Module(new EthernetDmaFrameAdapter)
    val tx: EthernetFrameTransmitter = if (macTxSlots == 1) Module(new GmiiFrameTx())
        else Module(new QueuedGmiiFrameTx(frameSlots = macTxSlots))
    tx.io.byteStep.foreach(_ := true.B)
    tx.io.abort.foreach(_ := false.B)
    val rx = Module(new GmiiFrameRx())
    dma.io.control <> io.control
    io.memory <> dma.io.memory
    adapter.io.txData <> dma.io.txData
    adapter.io.txControl <> dma.io.txControl
    dma.io.rxData <> adapter.io.rxData
    dma.io.rxStatus <> adapter.io.rxStatus
    tx.io.frame <> adapter.io.txFrame
    adapter.io.rxFrame <> rx.io.frame
    tx.io.enable := true.B
    rx.io.enable := true.B
    rx.io.promiscuous := false.B
    rx.io.broadcastEnable := true.B
    rx.io.macAddress := "h021122334455".U
    rx.io.gmiiData := io.gmiiRxData
    rx.io.gmiiValid := io.gmiiRxValid
    rx.io.gmiiError := io.gmiiRxError
    io.gmiiTxData := tx.io.gmiiData
    io.gmiiTxEnable := tx.io.gmiiEnable
    io.gmiiTxError := tx.io.gmiiError
    io.irq := dma.io.irq
    io.active := dma.io.active
    io.txBusy := tx.io.busy
    io.txDone := tx.io.done
    io.txDmaOverlap := tx.io.frame.fire && tx.io.gmiiEnable
    io.memoryReadOverlap := dma.io.memory.request.fire && !dma.io.memory.request.bits.write && tx.io.gmiiEnable
    io.txRejected := tx.io.rejected
    io.rxAccepted := rx.io.accepted
    io.rxDropped := rx.io.dropped
}

object SelfGmacFramesGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new SelfGmacFramesGsim(args.lift(1).map(_.toInt).getOrElse(4)), Array("--target-dir", args.head))
}
object SelfGmacAdapterGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetDmaFrameAdapter, Array("--target-dir", args.head))
}
object SelfGmacDmaGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new SelfGmacDmaGsim(args.lift(1).map(_.toInt).getOrElse(0), args.lift(2).map(_.toInt).getOrElse(1)), Array("--target-dir", args.head))
}
object SelfGmacFramesRtlMain extends App {
    require(args.length == 1)
    val options = Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info")
    ChiselStage.emitSystemVerilogFile(new GmiiFrameTx, Array("--target-dir", args.head + "/tx"), options)
    ChiselStage.emitSystemVerilogFile(new GmiiFrameRx, Array("--target-dir", args.head + "/rx"), options)
    ChiselStage.emitSystemVerilogFile(new EthernetDmaFrameAdapter,
        Array("--target-dir", args.head + "/adapter"), options)
    ChiselStage.emitSystemVerilogFile(new SelfGmacDmaGsim(args.lift(1).map(_.toInt).getOrElse(0)),
        Array("--target-dir", args.head + "/single-clock-dma"), options)
}
