package ip

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.ip.bus.{RegisterPort, CdcResetRelease}
import soc.ip.dma.{EthernetAxisWord, EthernetPacketDma}
import soc.ip.ethernet.{EthernetDmaFrameAdapter, GmiiFrameRx, EthernetFrameClockBridge}

/** Actual independent-clock MAC -> existing production 16-entry bridge -> DMA.
 * Observer ports carry no functional feedback. No PHY/Home/DDR/CPU included.
 */
class GmiiFrameRx125MHz(prefetch: Boolean) extends GmiiFrameRx(readPrefetch = prefetch)
class EthernetPacketDma100MHz(prefetch: Boolean) extends EthernetPacketDma(ramBytes = 65536, rxWritePrefetch = prefetch)
class EthernetClockedRx(macPrefetch: Boolean, dmaPrefetch: Boolean) extends RawModule {
    val clockMac = IO(Input(Clock()))
    val clockDma = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val macRelease = Module(new CdcResetRelease)
    macRelease.clockIn := clockMac; macRelease.asyncReset := commonReset
    val dmaRelease = Module(new CdcResetRelease)
    dmaRelease.clockIn := clockDma; dmaRelease.asyncReset := commonReset
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val memory = new RegisterPort
        val gmiiData = Input(UInt(8.W))
        val gmiiValid = Input(Bool())
        val gmiiError = Input(Bool())
        val cdcSourceIdle = Output(Bool())
        val cdcDestinationIdle = Output(Bool())
        val macFrameValid = Output(Bool())
        val macFrameReady = Output(Bool())
        val macFrameBits = Output(UInt(38.W))
        val cdcFrameValid = Output(Bool())
        val cdcFrameReady = Output(Bool())
        val cdcFrameBits = Output(UInt(38.W))
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
    val dma = withClockAndReset(clockDma, dmaRelease.resetOut) { Module(new EthernetPacketDma100MHz(dmaPrefetch)) }
    dma.io.control <> io.control
    io.memory <> dma.io.memory
    dma.io.txData.ready := true.B
    dma.io.txControl.ready := true.B
    val mac = withClockAndReset(clockMac, macRelease.resetOut) { Module(new GmiiFrameRx125MHz(macPrefetch)) }
    val adapter = withClockAndReset(clockDma, dmaRelease.resetOut) { Module(new EthernetDmaFrameAdapter) }
    val bridge = Module(new EthernetFrameClockBridge(16))
    bridge.sourceClock := clockMac; bridge.destinationClock := clockDma; bridge.commonReset := commonReset
    bridge.source <> mac.io.frame
    adapter.io.rxFrame <> bridge.destination
    mac.io.gmiiData := io.gmiiData; mac.io.gmiiValid := io.gmiiValid; mac.io.gmiiError := io.gmiiError
    mac.io.enable := true.B; mac.io.promiscuous := false.B
    mac.io.broadcastEnable := true.B; mac.io.macAddress := "h021122334455".U
    dma.io.rxData <> adapter.io.rxData; dma.io.rxStatus <> adapter.io.rxStatus
    adapter.io.txData.valid := false.B; adapter.io.txData.bits := 0.U.asTypeOf(adapter.io.txData.bits)
    adapter.io.txControl.valid := false.B; adapter.io.txControl.bits := 0.U.asTypeOf(adapter.io.txControl.bits)
    adapter.io.txFrame.ready := true.B
    io.accepted := mac.io.accepted; io.dropped := mac.io.dropped
    io.macOccupied := BoringUtils.bore(mac.occupied)
    io.macPending := BoringUtils.bore(mac.readPrefetchPending)
    io.bankRelease := mac.io.frame.fire && mac.io.frame.bits.last
    io.macPrefetchOccupied := BoringUtils.bore(mac.readPrefetchOccupancy)
    io.cdcSourceIdle := bridge.sourceIdle; io.cdcDestinationIdle := bridge.destinationIdle
    io.macFrameValid := bridge.source.valid; io.macFrameReady := bridge.source.ready
    io.macFrameBits := bridge.source.bits.asUInt
    io.cdcFrameValid := bridge.destination.valid; io.cdcFrameReady := bridge.destination.ready
    io.cdcFrameBits := bridge.destination.bits.asUInt
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
object EthernetClockedRxMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetClockedRx(args(1) == "1", args(2) == "1"),
        Array("--target-dir", args(0)))
}
