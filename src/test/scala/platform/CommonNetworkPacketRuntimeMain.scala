package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.dma.EthernetPacketDma
import soc.ip.ethernet._
import soc.platform._

/** Real packet admission and ownership chain, with three independent clocks.
  * The external RegisterPort memory endpoint is an explicit ordered test model,
  * not a CPU, Home, DDR, or a fabricated fabric completion acknowledgement.
  * Test stalls interpose on real ready/valid boundaries without dropping owners.
  */
class CommonNetworkPacketRuntimeFixture extends RawModule {
    val fabricClock = IO(Input(Clock()))
    val rxClock = IO(Input(Clock()))
    val txClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val memory = new RegisterPort
        val prepareValid = Input(Bool())
        val prepareEpoch = Input(UInt(8.W))
        val prepareReady = Output(Bool())
        val downstreamPrepareValid = Output(Bool())
        val downstreamPrepareReady = Input(Bool())
        val downstreamPrepareEpoch = Output(UInt(8.W))
        // Explicit endpoint-model receipts; no claim that these are AON/Home.
        val terminalConsumedAtAon = Input(Bool())
        val retired = Input(Bool())
        val retirementPermit = Output(Bool())
        val epochBusy = Output(Bool())
        val epochHeld = Output(Bool())
        val epochHeldValue = Output(UInt(8.W))
        val runtimePause = Output(Bool())
        val rxStopRequest = Output(Bool())
        val txStopRequest = Output(Bool())
        val holdRxStatusLast = Input(Bool())
        val holdTxControlLast = Input(Bool())
        val holdTxDataLast = Input(Bool())
        val gmiiRxData = Input(UInt(8.W))
        val gmiiRxValid = Input(Bool())
        val gmiiRxError = Input(Bool())
        val gmiiTxData = Output(UInt(8.W))
        val gmiiTxEnable = Output(Bool())
        val gmiiTxError = Output(Bool())
        val dmaActive = Output(Bool())
        val dmaTxIdle = Output(Bool())
        val dmaOwnersIdle = Output(Bool())
        val rxDrained = Output(Bool())
        val txDrained = Output(Bool())
        val released = Output(Bool())
        val rxAdmissionClosed = Output(Bool())
        val rxAccepted = Output(Bool())
        val rxDropped = Output(Bool())
        val rxDropReasons = Output(UInt(8.W))
        val rxBadFcs = Output(Bool())
        val txBusy = Output(Bool())
        val txDone = Output(Bool())
        val rxStatusLastBlocked = Output(Bool())
        val txControlLastBlocked = Output(Bool())
        val txDataLastBlocked = Output(Bool())
        val rxDataFire = Output(Bool())
        val rxDataLastFire = Output(Bool())
        val rxStatusFire = Output(Bool())
        val rxStatusData = Output(UInt(32.W))
        val rxStatusLastFire = Output(Bool())
        val txControlFire = Output(Bool())
        val txDataFire = Output(Bool())
        val txDataLastFire = Output(Bool())
        val rxDestinationIdle = Output(Bool())
        val txSourceIdle = Output(Bool())
    })
    def resetFor(clock: Clock): AsyncReset = {
        val r = Module(new CdcResetRelease)
        r.clockIn := clock
        r.asyncReset := commonColdReset
        r.resetOut
    }
    val fabricReset = resetFor(fabricClock)
    val rxReset = resetFor(rxClock)
    val txReset = resetFor(txClock)
    val boundary = CommonCpuTilePortParams(runtimeMaintenance = true,
        runtimeCancellation = true, runtimeInterruptHold = true)
    val sequencer = withClockAndReset(fabricClock, fabricReset) {
        Module(new CommonNetworkRuntimeSequencer(boundary))
    }
    sequencer.io.upstreamPrepare.valid := io.prepareValid
    sequencer.io.upstreamPrepare.bits.epoch := io.prepareEpoch
    sequencer.io.upstreamPrepare.bits.invalidateInstructions := true.B
    sequencer.io.upstreamPrepare.bits.invalidateTranslations := true.B
    io.prepareReady := sequencer.io.upstreamPrepare.ready
    io.downstreamPrepareValid := sequencer.io.downstreamPrepare.valid
    io.downstreamPrepareEpoch := sequencer.io.downstreamPrepare.bits.epoch
    sequencer.io.downstreamPrepare.ready := io.downstreamPrepareReady
    sequencer.io.terminalConsumedAtAon := io.terminalConsumedAtAon
    sequencer.io.retired := io.retired
    sequencer.io.fault := false.B
    io.retirementPermit := sequencer.io.retirementPermit
    io.epochBusy := sequencer.io.busy
    io.epochHeld := sequencer.io.held.valid
    io.epochHeldValue := sequencer.io.held.bits
    io.runtimePause := sequencer.io.dmaPause
    io.rxStopRequest := sequencer.io.rxStop
    io.txStopRequest := sequencer.io.txStop
    val dma = withClockAndReset(fabricClock, fabricReset) {
        Module(new EthernetPacketDma(ramBase = BigInt("80200000", 16), ramBytes = 65536,
            maxFrameBytes = 256, postedRxSlots = 4, memoryCredits = 4, postedTxSlots = 4,
            runtimeAdmission = true))
    }
    val adapter = withClockAndReset(fabricClock, fabricReset) { Module(new EthernetDmaFrameAdapter(true)) }
    val rx = withClockAndReset(rxClock, rxReset) {
        Module(new GmiiFrameRx(256, admissionStop = true, frameSlots = 4, diagnostics = true))
    }
    val tx = withClockAndReset(txClock, txReset) { Module(new GmiiFrameTx(256)) }
    val rxBridge = Module(new EthernetFrameClockBridge(4))
    rxBridge.sourceClock := rxClock
    rxBridge.destinationClock := fabricClock
    rxBridge.commonReset := commonColdReset
    val txBridge = Module(new EthernetFrameClockBridge(4))
    txBridge.sourceClock := fabricClock
    txBridge.destinationClock := txClock
    txBridge.commonReset := commonColdReset
    val stop = Module(new EthernetRxAdmissionStop)
    stop.sourceClock := fabricClock
    stop.destinationClock := rxClock
    stop.commonReset := commonColdReset
    stop.requested := io.rxStopRequest
    stop.destinationFrameIdle := !rx.io.ownedBusy.get
    stop.destinationFifoIdle := rxBridge.sourceIdle
    stop.sourceDrained := rxBridge.destinationIdle && adapter.io.rxIdle
    rx.io.stopNewFrames.get := stop.stopNewFrames
    rx.io.gmiiData := io.gmiiRxData
    rx.io.gmiiValid := io.gmiiRxValid
    rx.io.gmiiError := io.gmiiRxError
    rx.io.enable := true.B
    rx.io.promiscuous := true.B
    rx.io.broadcastEnable := true.B
    rx.io.macAddress := "h020000000001".U
    rxBridge.source <> rx.io.frame
    adapter.io.rxFrame <> rxBridge.destination
    dma.io.control <> io.control
    io.memory <> dma.io.memory
    dma.io.runtimePause.get := io.runtimePause
    dma.io.rxData <> adapter.io.rxData
    dma.io.rxStatus <> adapter.io.rxStatus
    val statusAllow = !io.holdRxStatusLast || !adapter.io.rxStatus.bits.last
    dma.io.rxStatus.valid := adapter.io.rxStatus.valid && statusAllow
    adapter.io.rxStatus.ready := dma.io.rxStatus.ready && statusAllow
    adapter.io.txData <> dma.io.txData
    adapter.io.txControl <> dma.io.txControl
    val controlAllow = !io.holdTxControlLast || !dma.io.txControl.bits.last
    adapter.io.txControl.valid := dma.io.txControl.valid && controlAllow
    dma.io.txControl.ready := adapter.io.txControl.ready && controlAllow
    val dataAllow = !io.holdTxDataLast || !dma.io.txData.bits.last
    adapter.io.txData.valid := dma.io.txData.valid && dataAllow
    dma.io.txData.ready := adapter.io.txData.ready && dataAllow
    adapter.io.stopNewTx.get := io.txStopRequest
    txBridge.source <> adapter.io.txFrame
    tx.io.frame <> txBridge.destination
    tx.io.enable := true.B
    val wireIdle = Module(new CdcLevel)
    wireIdle.clockIn := fabricClock
    wireIdle.resetIn := fabricReset
    val txLocalIdle = withClockAndReset(txClock, txReset) {
        RegNext(txBridge.destinationIdle && !tx.io.busy, false.B)
    }
    wireIdle.levelIn := txLocalIdle
    io.txDrained := adapter.io.txIdle && txBridge.sourceIdle && wireIdle.levelOut
    sequencer.io.dmaTxIdle := dma.io.runtimeTxIdle.get
    sequencer.io.dmaOwnersIdle := dma.io.runtimeOwnersIdle.get
    sequencer.io.macTxDrained := io.txDrained
    sequencer.io.macRxDrained := stop.drained
    sequencer.io.macReleased := io.released
    io.rxDrained := stop.drained
    io.released := !io.rxStopRequest && !io.txStopRequest && stop.settled
    io.dmaTxIdle := dma.io.runtimeTxIdle.get
    io.dmaOwnersIdle := dma.io.runtimeOwnersIdle.get
    io.dmaActive := dma.io.active
    io.rxAdmissionClosed := stop.stopNewFrames
    io.rxAccepted := rx.io.accepted
    io.rxDropped := rx.io.dropped
    io.rxDropReasons := rx.io.dropReasons.get
    io.rxBadFcs := rx.io.badFcs
    io.txBusy := tx.io.busy
    io.txDone := tx.io.done
    io.gmiiTxData := tx.io.gmiiData
    io.gmiiTxEnable := tx.io.gmiiEnable
    io.gmiiTxError := tx.io.gmiiError
    io.rxStatusLastBlocked := adapter.io.rxStatus.valid && adapter.io.rxStatus.bits.last && !statusAllow
    io.txControlLastBlocked := dma.io.txControl.valid && dma.io.txControl.bits.last && !controlAllow
    io.txDataLastBlocked := dma.io.txData.valid && dma.io.txData.bits.last && !dataAllow
    io.rxDataFire := dma.io.rxData.fire
    io.rxDataLastFire := dma.io.rxData.fire && dma.io.rxData.bits.last
    io.rxStatusFire := dma.io.rxStatus.fire
    io.rxStatusData := dma.io.rxStatus.bits.data
    io.rxStatusLastFire := dma.io.rxStatus.fire && dma.io.rxStatus.bits.last
    io.txControlFire := dma.io.txControl.fire
    io.txDataFire := dma.io.txData.fire
    io.txDataLastFire := dma.io.txData.fire && dma.io.txData.bits.last
    io.rxDestinationIdle := rxBridge.destinationIdle
    io.txSourceIdle := txBridge.sourceIdle
}

object CommonNetworkPacketRuntimeNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonNetworkPacketRuntimeFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
