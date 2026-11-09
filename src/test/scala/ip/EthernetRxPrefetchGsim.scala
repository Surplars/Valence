package ip

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.ip.bus.RegisterPort
import soc.ip.dma.{EthernetAxisWord, EthernetPacketDma}
import soc.ip.ethernet.{EthernetDmaFrameAdapter, GmiiFrameRx}

/** Common-clock isolated MAC/DMA path or direct AXIS diagnostic; no CDC/CPU/home/PHY. */
class EthernetRxPrefetchGsim(macPrefetch: Boolean, dmaPrefetch: Boolean, axisOnly: Boolean) extends Module {
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val memory = new RegisterPort
        val gmiiData = Input(UInt(8.W))
        val gmiiValid = Input(Bool())
        val gmiiError = Input(Bool())
        val rxData = Flipped(Decoupled(new EthernetAxisWord))
        val rxStatus = Flipped(Decoupled(new EthernetAxisWord))
        val accepted = Output(Bool())
        val dropped = Output(Bool())
        val dataFire = Output(Bool())
        val dataWord = Output(UInt(32.W))
        val dataKeep = Output(UInt(4.W))
        val statusWord = Output(UInt(32.W))
        val statusKeep = Output(UInt(4.W))
        val dmaState = Output(UInt(3.W))
        val macPending = Output(Bool())
        val dmaPending = Output(Bool())
        val bankRelease = Output(Bool())
        val dataLast = Output(Bool())
        val statusFire = Output(Bool())
        val statusLast = Output(Bool())
        val collectDone = Output(Bool())
        val completion = Output(Bool())
        val failed = Output(Bool())
        val activeAddress = Output(UInt(64.W))
        val activeBytes = Output(UInt(17.W))
        val owned = Output(UInt(3.W))
        val completed = Output(UInt(3.W))
        val pending = Output(UInt(3.W))
        val outstanding = Output(UInt(10.W))
        val macOccupied = Output(UInt(3.W))
        val macPrefetchOccupied = Output(UInt(2.W))
        val dmaPrefetchOccupied = Output(UInt(3.W))
        val creditStall = Output(Bool())
        val storeEmpty = Output(Bool())
    })
    val dma = Module(new EthernetPacketDma(ramBytes = 65536, rxWritePrefetch = dmaPrefetch))
    dma.io.control <> io.control
    io.memory <> dma.io.memory
    dma.io.txData.ready := true.B
    dma.io.txControl.ready := true.B
    io.accepted := false.B; io.dropped := false.B
    io.macOccupied := 0.U; io.macPrefetchOccupied := 0.U; io.macPending := false.B; io.bankRelease := false.B
    if (axisOnly) {
        dma.io.rxData <> io.rxData
        dma.io.rxStatus <> io.rxStatus
    } else {
        io.rxData.ready := false.B; io.rxStatus.ready := false.B
        val mac = Module(new GmiiFrameRx(readPrefetch = macPrefetch))
        val adapter = Module(new EthernetDmaFrameAdapter)
        mac.io.gmiiData := io.gmiiData; mac.io.gmiiValid := io.gmiiValid; mac.io.gmiiError := io.gmiiError
        mac.io.enable := true.B; mac.io.promiscuous := false.B
        mac.io.broadcastEnable := true.B; mac.io.macAddress := "h021122334455".U
        adapter.io.rxFrame <> mac.io.frame
        dma.io.rxData <> adapter.io.rxData; dma.io.rxStatus <> adapter.io.rxStatus
        adapter.io.txData.valid := false.B; adapter.io.txData.bits := 0.U.asTypeOf(adapter.io.txData.bits)
        adapter.io.txControl.valid := false.B; adapter.io.txControl.bits := 0.U.asTypeOf(adapter.io.txControl.bits)
        adapter.io.txFrame.ready := true.B
        io.accepted := mac.io.accepted; io.dropped := mac.io.dropped
        io.macOccupied := BoringUtils.bore(mac.occupied)
        io.macPending := BoringUtils.bore(mac.readPrefetchPending)
        io.bankRelease := mac.io.frame.fire && mac.io.frame.bits.last
        io.macPrefetchOccupied := BoringUtils.bore(mac.readPrefetchOccupancy)
    }
    io.dataWord := dma.io.rxData.bits.data; io.dataKeep := dma.io.rxData.bits.keep
    io.statusWord := dma.io.rxStatus.bits.data; io.statusKeep := dma.io.rxStatus.bits.keep
    io.dmaState := BoringUtils.bore(dma.rxState); io.dmaPending := BoringUtils.bore(dma.rxPrefetchPending)
    io.dataFire := dma.io.rxData.fire; io.dataLast := dma.io.rxData.bits.last
    io.statusFire := dma.io.rxStatus.fire; io.statusLast := dma.io.rxStatus.bits.last
    io.collectDone := BoringUtils.bore(dma.rxDataDone) && BoringUtils.bore(dma.rxStatusDone)
    io.completion := BoringUtils.bore(dma.complete)
    io.failed := BoringUtils.bore(dma.rxFailed)
    io.activeAddress := BoringUtils.bore(dma.rxAddress)
    io.activeBytes := BoringUtils.bore(dma.rxBytes)
    io.owned := BoringUtils.bore(dma.ownedCount)
    io.completed := BoringUtils.bore(dma.completedCount)
    io.pending := BoringUtils.bore(dma.pendingCount)
    io.outstanding := BoringUtils.bore(dma.rxIssued) - BoringUtils.bore(dma.rxReplied)
    io.dmaPrefetchOccupied := BoringUtils.bore(dma.rxPrefetchOccupancy)
    io.creditStall := BoringUtils.bore(dma.rxState) === 4.U && io.outstanding === 4.U
    io.storeEmpty := BoringUtils.bore(dma.rxState) === 4.U && !dma.io.memory.request.valid && io.outstanding < 4.U
}
object EthernetRxPrefetchGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetRxPrefetchGsim(args(1) == "1", args(2) == "1", args(3) == "1"),
        Array("--target-dir", args(0)))
}

object EthernetRxPrefetchPacketMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetPacketDma(ramBytes = 8192, rxWritePrefetch = args(1) == "1"),
        Array("--target-dir", args(0)))
}
