package soc.ip.ethernet

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.bus._
import soc.ip.clock._
import soc.ip.dma.{EthernetAxisWord, NetworkDmaConfig}

/** Opt-in tri-speed/full-duplex endpoint with explicit byte-rate adaptation.
  * CPU control stays on. TX/RX stop independently only after frame/FIFO/config/
  * statistics/adapter tails AND CPU admission handshake have completely drained.
  * PHY raw RX capture stays on; fixed ingress delay preserves the first frame.
  * Physical IDDR/ODDR/delays stay in native_rgmii_trispeed. The RX clock must
  * come directly from a recovered-clock BUFG, never a fixed-125 MHz RX MMCM.
  * RTL/simulation do not establish I/O timing, placement or board qualification.
  */
class TriSpeedManagedGmac(cpuHz: Int = 100000000, aonHz: Int = 50000000,
    mediaHz: Int = 125000000, hardwareClocks: Boolean = true,
    networkDmaConfig: NetworkDmaConfig = NetworkDmaConfig.Default, txFrameSlots: Int = 1) extends RawModule {
    require(txFrameSlots == 1 || txFrameSlots == 2, "tri-speed TX supports one or two frame banks")
    require(mediaHz == 125000000, "tri-speed TX uses a continuous 125 MHz reference")
    val sourceClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val streams = IO(new ManagedGmacStreams)
    val control = IO(Flipped(Vec(2, new ClockResourceControl)))
    val txClock = IO(Output(Clock()))
    val rxClock = IO(Output(Clock()))
    val gmiiTxData = IO(Output(UInt(8.W)))
    val gmiiTxEnable = IO(Output(Bool()))
    val gmiiTxError = IO(Output(Bool()))
    val rawRgmiiRxRise = IO(Input(UInt(5.W)))
    val rawRgmiiRxFall = IO(Input(UInt(5.W)))
    val rgmiiTxRise = IO(Output(UInt(5.W)))
    val rgmiiTxFall = IO(Output(UInt(5.W)))
    val rgmiiTxClockRise = IO(Output(Bool()))
    val rgmiiTxClockFall = IO(Output(Bool()))
    val linkUp = IO(Output(Bool()))
    val requestedSpeed = IO(Output(UInt(2.W)))
    val appliedSpeed = IO(Output(UInt(2.W)))
    val mediaPending = IO(Output(Bool()))
    val txIdle = IO(Output(Bool()))
    val rxDrained = IO(Output(Bool()))
    val mdc = IO(Output(Bool()))
    val mdioIn = IO(Input(Bool()))
    val mdioOut = IO(Output(Bool()))
    val mdioOe = IO(Output(Bool()))
    val irq = IO(Output(Bool()))
    val localIdle = IO(Output(Vec(2, Bool())))
    val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := sourceClock
    cpuRelease.asyncReset := commonReset
    val phy = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(new Rtl8211fPhyManager(cpuHz, startupCycles = cpuHz / 20, pollCycles = cpuHz / 10))
    }
    val media = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(new EthernetMediaTransition(cpuHz / 2))
    }
    val rxClockWatchdog = Module(new EthernetRxClockWatchdog(cpuHz / 1000))
    rxClockWatchdog.sourceClock := rawRxClock
    rxClockWatchdog.monitorClock := sourceClock
    rxClockWatchdog.commonReset := commonReset
    media.io.requestedLink := phy.io.linkUp && rxClockWatchdog.present
    media.io.requestedSpeed := phy.io.requestedSpeed
    requestedSpeed := phy.io.requestedSpeed
    appliedSpeed := media.io.appliedSpeed
    linkUp := media.io.linkUp
    mediaPending := media.io.pending
    def gated(raw: Clock, index: Int): Clock = if (hardwareClocks) {
        val gate = Module(new ManagedClockBuffer)
        gate.rawClock := raw
        gate.commonReset := commonReset
        gate.enable := control(index).clockEnable
        gate.managedClock
    } else raw
    val txManaged = gated(rawTxClock, 0)
    // Completed packet RAM/readout must keep progressing if PHY RXC stops.
    // Only the physical decoder/packer below use recovered rawRxClock.
    val rxManaged = gated(rawTxClock, 1)
    txClock := txManaged
    rxClock := rxManaged
    val txRelease = Module(new CdcResetRelease)
    txRelease.clockIn := txManaged
    txRelease.asyncReset := commonReset
    val rxRelease = Module(new CdcResetRelease)
    rxRelease.clockIn := rxManaged
    rxRelease.asyncReset := commonReset
    val rawTxRelease = Module(new CdcResetRelease)
    rawTxRelease.clockIn := rawTxClock
    rawTxRelease.asyncReset := commonReset
    val rawRxRelease = Module(new CdcResetRelease)
    rawRxRelease.clockIn := rawRxClock
    rawRxRelease.asyncReset := commonReset
    val encode = withClockAndReset(rawTxClock, rawTxRelease.resetOut) { Module(new TriSpeedRgmiiTx) }
    val decode = withClockAndReset(rawRxClock, rawRxRelease.resetOut) { Module(new TriSpeedRgmiiRx) }
    val txRate = Module(new CdcMailbox(2))
    val rxRate = Module(new CdcMailbox(2))
    txRate.sourceClock := sourceClock
    txRate.destinationClock := rawTxClock
    txRate.commonReset := commonReset
    rxRate.sourceClock := sourceClock
    rxRate.destinationClock := rawRxClock
    rxRate.commonReset := commonReset
    txRate.source <> media.io.txRate
    rxRate.source <> media.io.rxRate
    encode.io.rate <> txRate.destination
    decode.io.rate <> rxRate.destination
    media.io.txRateIdle := txRate.sourceIdle
    media.io.rxRateIdle := rxRate.sourceIdle
    val txAbort = ManagedPeripheralSupport.level(media.io.abortTraffic, txManaged, txRelease.resetOut)
    val rxAbort = ManagedPeripheralSupport.level(media.io.abortTraffic, rxManaged, rxRelease.resetOut)
    val rawRxAbort = ManagedPeripheralSupport.level(media.io.abortTraffic, rawRxClock, rawRxRelease.resetOut)
    val txLink = ManagedPeripheralSupport.level(media.io.linkUp, txManaged, txRelease.resetOut)
    val rxLink = ManagedPeripheralSupport.level(media.io.linkUp, rxManaged, rxRelease.resetOut)
    decode.io.abort := rawRxAbort
    decode.io.admissionClosed := rawRxAbort
    decode.io.rise := rawRgmiiRxRise
    decode.io.fall := rawRgmiiRxFall
    val physicalIngress = Module(new EthernetPhysicalIngress(64))
    physicalIngress.sourceClock := rawRxClock
    physicalIngress.destinationClock := rawTxClock
    physicalIngress.commonReset := (commonReset.asBool || media.io.ingressReset).asAsyncReset
    physicalIngress.sourceData := decode.io.gmiiData
    physicalIngress.sourceValid := decode.io.gmiiValid
    physicalIngress.sourceError := decode.io.gmiiError
    physicalIngress.sourceByteStep := decode.io.byteStep
    physicalIngress.physicalValid := rawRgmiiRxRise(4)
    physicalIngress.captureEnable := ManagedPeripheralSupport.level(media.io.linkUp, rawRxClock, rawRxRelease.resetOut)
    val sourceEpochReady = ManagedPeripheralSupport.level(physicalIngress.sourceReady,
        sourceClock, cpuRelease.resetOut)
    val destinationEpochReady = ManagedPeripheralSupport.level(physicalIngress.destinationReady,
        sourceClock, cpuRelease.resetOut)
    media.io.ingressReady := sourceEpochReady && destinationEpochReady
    rgmiiTxRise := encode.io.rise
    rgmiiTxFall := encode.io.fall
    rgmiiTxClockRise := encode.io.clockRise
    rgmiiTxClockFall := encode.io.clockFall
    val txQ = ManagedPeripheralSupport.level(control(0).quiesce, sourceClock, cpuRelease.resetOut)
    val txIso = ManagedPeripheralSupport.level(control(0).isolate, sourceClock, cpuRelease.resetOut)
    val rxQ = ManagedPeripheralSupport.level(control(1).quiesce, sourceClock, cpuRelease.resetOut)
    val adapter = withClockAndReset(sourceClock, cpuRelease.resetOut) { Module(new EthernetDmaFrameAdapter(true)) }
    adapter.io.txData <> streams.txData
    adapter.io.txControl <> streams.txControl
    streams.rxData <> adapter.io.rxData
    streams.rxStatus <> adapter.io.rxStatus
    adapter.io.stopNewTx.get := txQ || txIso || media.io.stopNewTraffic
    val txFifo = Module(new EthernetFrameClockBridge(16))
    txFifo.sourceClock := sourceClock
    txFifo.destinationClock := txManaged
    txFifo.commonReset := commonReset
    txFifo.source <> adapter.io.txFrame
    val rxFifo = Module(new EthernetFrameClockBridge(16))
    rxFifo.sourceClock := rxManaged
    rxFifo.destinationClock := sourceClock
    rxFifo.commonReset := commonReset
    adapter.io.rxFrame <> rxFifo.destination
    val tx: EthernetFrameTransmitter = withClockAndReset(txManaged, txRelease.resetOut) {
        if (txFrameSlots == 1) Module(new GmiiFrameTx(networkDmaConfig.maxFrameBytes, rateAdaptation = true))
        else Module(new QueuedGmiiFrameTx(networkDmaConfig.maxFrameBytes, txFrameSlots))
    }
    val rx = withClockAndReset(rxManaged, rxRelease.resetOut) { Module(new GmiiFrameRx(maxFrameBytes = networkDmaConfig.maxFrameBytes, admissionStop = true,
        frameSlots = networkDmaConfig.macRxSlots, rateAdaptation = true, diagnostics = true)) }
    tx.io.frame <> txFifo.destination
    rxFifo.source <> rx.io.frame
    tx.io.byteStep.get := encode.io.byteStep
    tx.io.abort.get := txAbort
    rx.io.abort.get := rxAbort
    encode.io.datapathIdle := !tx.io.busy && txFifo.destinationIdle
    encode.io.gmiiData := tx.io.gmiiData
    encode.io.gmiiEnable := tx.io.gmiiEnable
    encode.io.gmiiError := tx.io.gmiiError
    val txConfig = Module(new EthernetConfigClockBridge)
    val rxConfig = Module(new EthernetConfigClockBridge)
    txConfig.sourceClock := sourceClock
    txConfig.destinationClock := txManaged
    txConfig.commonReset := commonReset
    rxConfig.sourceClock := sourceClock
    rxConfig.destinationClock := rxManaged
    rxConfig.commonReset := commonReset
    val txStats = Module(new CdcCounterBank(5))
    val rxStats = Module(new CdcCounterBank(5))
    txStats.sourceClock := txManaged
    txStats.destinationClock := sourceClock
    txStats.commonReset := commonReset
    rxStats.sourceClock := rxManaged
    rxStats.destinationClock := sourceClock
    rxStats.commonReset := commonReset
    txStats.increment(0) := tx.io.done
    txStats.increment(1) := tx.io.rejected
    txStats.increment(2) := Mux(tx.io.done, tx.io.bytes, 0.U)
    txStats.increment(3) := tx.io.aborted.get
    txStats.increment(4) := txFifo.destination.valid && !txFifo.destination.ready
    rxStats.increment(0) := rx.io.accepted
    rxStats.increment(1) := rx.io.dropped
    rxStats.increment(2) := rx.io.badFcs
    rxStats.increment(3) := Mux(rx.io.accepted, rx.io.bytes, 0.U)
    rxStats.increment(4) := rxFifo.source.valid && !rxFifo.source.ready
    txStats.delta.ready := true.B
    rxStats.delta.ready := true.B
    val rxDiagnostics = Module(new CdcCounterBank(8))
    rxDiagnostics.sourceClock := rxManaged
    rxDiagnostics.destinationClock := sourceClock
    rxDiagnostics.commonReset := commonReset
    for (n <- 0 until 8) rxDiagnostics.increment(n) := rx.io.dropReasons.get(n)
    rxDiagnostics.delta.ready := true.B
    val rawDiagnostics = Module(new CdcCounterBank(3))
    rawDiagnostics.sourceClock := rawRxClock
    rawDiagnostics.destinationClock := sourceClock
    rawDiagnostics.commonReset := commonReset
    rawDiagnostics.increment(0) := decode.io.oddNibble
    rawDiagnostics.increment(1) := physicalIngress.wholeFrameSkipped
    rawDiagnostics.increment(2) := physicalIngress.overflow
    rawDiagnostics.delta.ready := true.B
    val tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)
    val config = GmacParams(controlClockHz = cpuHz, mdcHz = 1250000, aggregateStats = true, rxAdmissionStop = true,
        maxFrameBytes = networkDmaConfig.maxFrameBytes, rxFrameSlots = networkDmaConfig.macRxSlots,
        triSpeedExtensions = true, externalMdio = true)
    val frontend = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(new RegisterGmacControl(config.base, tlParams))
    }
    val csr = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(new TileLinkGmacControl(config, tlParams))
    }
    frontend.io.registers <> registers
    csr.io.tl <> frontend.io.tl
    val port = csr.io.ports.head
    // Conservative 400 ns read half-cycle includes the two-FF pad synchronizer
    // and RTL8211F MDIO response delay. mdioIn is the raw IOBUF input here.
    val mdio = withClockAndReset(sourceClock, cpuRelease.resetOut) { Module(new MdioClause22(cpuHz, 1250000)) }
    val mdioOwner = withClockAndReset(sourceClock, cpuRelease.resetOut) { Module(new ManagedMdioArbiter) }
    mdioOwner.io.policyCommand <> phy.io.command
    phy.io.response <> mdioOwner.io.policyResponse
    mdioOwner.io.policyLock := phy.io.lock
    mdioOwner.io.initialized := phy.io.initialized
    mdioOwner.io.softwareCommand <> port.mdioCommand.get
    port.mdioResponse.get <> mdioOwner.io.softwareResponse
    mdio.io.command <> mdioOwner.io.engineCommand
    mdioOwner.io.engineResponse <> mdio.io.response
    mdio.io.mdioIn := ManagedPeripheralSupport.level(mdioIn, sourceClock, cpuRelease.resetOut)
    mdc := mdio.io.mdc
    mdioOut := mdio.io.mdioOut
    mdioOe := mdio.io.mdioOe
    phy.io.restart := port.restartPhy.get
    val rxStop = Module(new EthernetRxAdmissionStop)
    rxStop.sourceClock := sourceClock
    rxStop.destinationClock := rxManaged
    rxStop.commonReset := commonReset
    rxStop.requested := port.rxStopRequest.get || media.io.stopNewTraffic
    rxStop.sourceDrained := adapter.io.rxIdle && rxFifo.destinationIdle
    rxStop.destinationFrameIdle := !rx.io.ownedBusy.get
    rxStop.destinationFifoIdle := rxFifo.sourceIdle
    rx.io.stopNewFrames.get := rxStop.stopNewFrames
    port.rxStopDrained.get := rxStop.drained
    val currentConfig = Wire(new EthernetConfigSnapshot)
    currentConfig.macAddress := port.macAddress
    currentConfig.txEnable := port.txEnable
    currentConfig.rxEnable := port.rxEnable
    currentConfig.promiscuous := port.promiscuous
    currentConfig.broadcastEnable := port.broadcastEnable
    val sentConfig = withClockAndReset(sourceClock, cpuRelease.resetOut) { RegInit(0.U(52.W)) }
    val dirty = currentConfig.asUInt =/= sentConfig
    txConfig.source.valid := dirty && rxConfig.source.ready
    rxConfig.source.valid := dirty && txConfig.source.ready
    txConfig.source.bits := currentConfig
    rxConfig.source.bits := currentConfig
    withClockAndReset(sourceClock, cpuRelease.resetOut) {
        when(txConfig.source.fire && rxConfig.source.fire) { sentConfig := currentConfig.asUInt }
    }
    txConfig.destination.ready := !tx.io.busy
    // With producer admission closed, unrelated physical traffic is discarded
    // and owns no payload/configuration. It cannot postpone shutdown forever.
    val rxConfigurationIdle = !rx.io.busy || (rxStop.stopNewFrames && !rx.io.ownedBusy.get)
    rxConfig.destination.ready := rxConfigurationIdle
    val txImage = withClockAndReset(txManaged, txRelease.resetOut) {
        val image = RegInit(0.U.asTypeOf(new EthernetConfigSnapshot))
        when(txConfig.destination.fire) { image := txConfig.destination.bits }
        image
    }
    val rxImage = withClockAndReset(rxManaged, rxRelease.resetOut) {
        val image = RegInit(0.U.asTypeOf(new EthernetConfigSnapshot))
        when(rxConfig.destination.fire) { image := rxConfig.destination.bits }
        image
    }
    tx.io.enable := txImage.txEnable && txLink
    rx.io.enable := rxImage.rxEnable && rxLink
    rx.io.promiscuous := rxImage.promiscuous
    rx.io.broadcastEnable := rxImage.broadcastEnable
    rx.io.macAddress := rxImage.macAddress
    val ingress = Module(new PeripheralWakeDelay(11,
        ManagedPeripheralSupport.wakeDelay(mediaHz, cpuHz, aonHz)))
    ingress.rawClock := rawTxClock
    ingress.commonReset := commonReset
    ingress.payload := Cat(physicalIngress.byteStep, physicalIngress.valid, physicalIngress.error, physicalIngress.data)
    ingress.active := physicalIngress.valid
    ingress.quiesce := control(1).quiesce
    ingress.isolate := control(1).isolate
    rx.io.gmiiData := ingress.delayed(7, 0)
    rx.io.gmiiError := ingress.delayed(8)
    rx.io.gmiiValid := ingress.delayed(9)
    rx.io.byteStep.get := ingress.delayed(10)
    val ingressEmpty = ManagedPeripheralSupport.level(ingress.empty, sourceClock, cpuRelease.resetOut)
    val txWireDrained = ManagedPeripheralSupport.level(!tx.io.busy && txFifo.destinationIdle && encode.io.idle,
        sourceClock, cpuRelease.resetOut)
    media.io.txDrained := adapter.io.txIdle && txFifo.sourceIdle && txWireDrained
    media.io.rxDrained := rxStop.drained && ingressEmpty
    txIdle := media.io.txDrained
    rxDrained := media.io.rxDrained
    gmiiTxData := tx.io.gmiiData
    gmiiTxEnable := tx.io.gmiiEnable
    gmiiTxError := tx.io.gmiiError
    val receiverWake = ManagedPeripheralSupport.level(ingress.wake, sourceClock, cpuRelease.resetOut)
    withClockAndReset(sourceClock, cpuRelease.resetOut) {
        control(0).wake := RegNext(dirty || media.io.pending || ((txQ || txIso) &&
            (streams.txData.valid || streams.txControl.valid)), false.B)
        control(1).wake := RegNext(dirty || media.io.pending || receiverWake || !rxStop.settled, false.B)
    }
    val txDrainCpu = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        RegNext(txQ && adapter.io.txIdle && txFifo.sourceIdle && txConfig.sourceIdle &&
            !dirty && txStats.destinationIdle, false.B)
    }
    val rxDrainCpu = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        RegNext(rxQ && adapter.io.rxIdle && rxFifo.destinationIdle && rxConfig.sourceIdle &&
            !dirty && rxStats.destinationIdle && rxDiagnostics.destinationIdle && rxStop.settled, false.B)
    }
    val txDrain = ManagedPeripheralSupport.level(txDrainCpu, txManaged, txRelease.resetOut)
    val rxDrain = ManagedPeripheralSupport.level(rxDrainCpu, rxManaged, rxRelease.resetOut)
    localIdle(0) := txDrain && !tx.io.busy && txFifo.destinationIdle && txStats.sourceIdle &&
        !txConfig.destination.valid
    localIdle(1) := rxDrain && !rx.io.busy && rxFifo.sourceIdle && rxStats.sourceIdle &&
        !rxConfig.destination.valid && ingress.empty && rxDiagnostics.sourceIdle
    for ((domainClock, n) <- Seq(txManaged, rxManaged).zipWithIndex) {
        val agent = Module(new PeripheralQuiesceAck)
        agent.domainClock := domainClock
        agent.commonReset := commonReset
        agent.quiesce := control(n).quiesce
        agent.idle := localIdle(n)
        control(n).ack := agent.ack
    }
    port.linkUp := media.io.linkUp
    val previousLink = withClockAndReset(sourceClock, cpuRelease.resetOut) { RegNext(port.linkUp, false.B) }
    val configPending = dirty || !txConfig.sourceIdle || !rxConfig.sourceIdle
    val txBusyLevel = withClockAndReset(txManaged, txRelease.resetOut) { RegNext(tx.io.busy, false.B) }
    val rxBusyLevel = withClockAndReset(rxManaged, rxRelease.resetOut) { RegNext(!rxConfigurationIdle, false.B) }
    port.txBusy := ManagedPeripheralSupport.level(txBusyLevel, sourceClock, cpuRelease.resetOut) ||
        !adapter.io.txIdle || !txFifo.sourceIdle || configPending
    port.rxBusy := ManagedPeripheralSupport.level(rxBusyLevel, sourceClock, cpuRelease.resetOut) || configPending ||
        !rxStop.settled || (port.rxStopRequest.get && !rxStop.drained)
    val txDelta = Mux(txStats.delta.valid, txStats.delta.bits.asUInt, 0.U).asTypeOf(Vec(5, UInt(32.W)))
    val rxDelta = Mux(rxStats.delta.valid, rxStats.delta.bits.asUInt, 0.U).asTypeOf(Vec(5, UInt(32.W)))
    val rawDelta = Mux(rawDiagnostics.delta.valid, rawDiagnostics.delta.bits.asUInt, 0.U)
        .asTypeOf(Vec(3, UInt(32.W)))
    val totalDrops = rxDelta(1) + rawDelta(1)
    port.deltas.get := VecInit(Seq(txDelta(0), rxDelta(0), totalDrops, rxDelta(2), txDelta(2), rxDelta(3)))
    port.events := Cat(port.linkUp =/= previousLink, txDelta(1).orR, rxDelta(2).orR,
        totalDrops.orR, rxDelta(0).orR, txDelta(0).orR)
    port.txBytes := 0.U
    port.rxBytes := 0.U
    val diagnosticDelta = Mux(rxDiagnostics.delta.valid, rxDiagnostics.delta.bits.asUInt, 0.U)
        .asTypeOf(Vec(8, UInt(32.W)))
    port.diagnosticDeltas.get := VecInit(diagnosticDelta.toSeq ++ Seq(txDelta(3), rxDelta(4), txDelta(4),
        rawDelta(0), rawDelta(2), rawDelta(1)))
    // Extension V1 in bits63:56. Bits0/1 PHY verified/link; requested3:2,
    // applied5:4; pending6, timeout7; PHY fault11:8; MAC ready12;
    // fully drained TX/RX13/14; recovered clock present15. Other bits zero.
    port.mediaStatus.get := (BigInt(1) << 56).U(64.W) |
        Cat(rxClockWatchdog.present, media.io.rxDrained, media.io.txDrained, media.io.linkUp, phy.io.fault,
            media.io.timedOut, media.io.pending, media.io.appliedSpeed, phy.io.requestedSpeed,
            phy.io.linkUp, phy.io.initialized)
    port.phyCounters.get(0) := Cat(phy.io.verifyErrorCount, phy.io.noAckCount)
    port.phyCounters.get(1) := Cat(phy.io.pollCount, phy.io.linkChangeCount)
    port.phyCounters.get(2) := Cat(media.io.timeoutCount, phy.io.unsupportedCount)
    port.mdioIn := true.B
    irq := csr.io.irq.orR
}
