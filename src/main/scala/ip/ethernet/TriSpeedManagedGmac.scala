package soc.ip.ethernet

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.bus._
import soc.ip.clock._
import soc.ip.dma.{EthernetAxisWord, NetworkDmaConfig}

/** Source-clock-domain payload admission barrier for runtime fabric transitions.
  * RX drain proves that admitted payload owners have retired, even if unrelated
  * physical frames keep arriving and are discarded with admission-closed counts.
  * TX stop may be requested only after previously admitted DMA TX work finishes;
  * TX drain then covers the adapter, FIFO, transmitter and physical encoder tail.
  * These are not full clock-gating ACKs: background statistics, configuration and
  * physical ingress remain governed by the existing CMU/media lifecycle proofs.
  */
class EthernetRuntimeAdmissionPort extends Bundle {
    val rxStopRequest = Input(Bool())
    val txStopRequest = Input(Bool())
    val rxDrained = Output(Bool())
    val txDrained = Output(Bool())
    val released = Output(Bool())
}

/** Optional fabric-control park, not a clock-gating or whole-system ACK.
  * Counters and their acknowledged snapshots remain owned while consumption
  * pauses. Fewer than 2^32 increments per field between snapshots is required.
  */
class EthernetRuntimeControlParkPort extends Bundle {
    val request = Input(Bool())
    // Same-source-clock consumption of request=false, NOT cross-domain gate ACK.
    val released = Output(Bool())
    val csrDrained = Output(Bool())
    val configDrained = Output(Bool())
    val mdioDrained = Output(Bool())
    val phyParked = Output(Bool())
    val phyFault = Output(UInt(4.W))
    val mediaSettled = Output(Bool())
    val statisticsPending = Output(UInt(4.W))
    val parked = Output(Bool())
}

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
    networkDmaConfig: NetworkDmaConfig = NetworkDmaConfig.Default, txFrameSlots: Int = 1,
    val rawClockHandoff: Boolean = false, balancedRawClock: Boolean = false,
    runtimeAdmission: Boolean = false, runtimeControlPark: Boolean = false,
    exportContinuousClock: Boolean = false) extends RawModule {
    require(!balancedRawClock || hardwareClocks)
    require(!(rawClockHandoff && balancedRawClock),
        "RAW MAC handoff with balanced raw clocks needs dedicated MAC lifecycle/CDC qualification")
    require(txFrameSlots == 1 || txFrameSlots == 2, "tri-speed TX supports one or two frame banks")
    require(mediaHz == 125000000, "tri-speed TX uses a continuous 125 MHz reference")
    val sourceClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val streams = IO(new ManagedGmacStreams)
    val runtimeAdmissionPort = if (runtimeAdmission) Some(IO(new EthernetRuntimeAdmissionPort)) else None
    val controlPark = if (runtimeControlPark) Some(IO(new EthernetRuntimeControlParkPort)) else None
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
    // Fixed raw TX capture/encoder and managed RX/TX are parallel buffered
    // leaves of the SAME clock input. No extra cascade on the raw clock.
    val continuousTxClock = if (balancedRawClock) {
        val keepRunning = Module(new ContinuousClockBuffer)
        keepRunning.rawClock := rawTxClock
        keepRunning.runningClock
    } else rawTxClock
    // Optional standalone fixed-source composition reuses this exact leaf.
    // Absent by default: no new production-default port or clock buffer.
    val continuousClock = if (exportContinuousClock) Some(IO(Output(Clock()))) else None
    continuousClock.foreach(_ := continuousTxClock)
    // Test subclasses may shorten only policy scheduling delays. Production
    // construction and MDIO serializer timing remain unchanged.
    protected def buildPhyManager(): Rtl8211fPhyManager =
        new Rtl8211fPhyManager(cpuHz, startupCycles = cpuHz / 20, pollCycles = cpuHz / 10,
            runtimePark = runtimeControlPark)
    val phy = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(buildPhyManager())
    }
    val parkControl = controlPark.map(_.request).getOrElse(false.B)
    phy.io.parkRequest.foreach(_ := parkControl)
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
        val gate = Module(new ManagedClockBuffer(independentControlClock = balancedRawClock))
        gate.rawClock := raw
        gate.controlClock.foreach(_ := continuousTxClock)
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
    rawTxRelease.clockIn := continuousTxClock
    rawTxRelease.asyncReset := commonReset
    val rawRxRelease = Module(new CdcResetRelease)
    rawRxRelease.clockIn := rawRxClock
    rawRxRelease.asyncReset := commonReset
    val encode = withClockAndReset(continuousTxClock, rawTxRelease.resetOut) { Module(new TriSpeedRgmiiTx) }
    val decode = withClockAndReset(rawRxClock, rawRxRelease.resetOut) { Module(new TriSpeedRgmiiRx) }
    val txRate = Module(new CdcMailbox(2))
    val rxRate = Module(new CdcMailbox(2))
    txRate.sourceClock := sourceClock
    txRate.destinationClock := continuousTxClock
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
    // One registered CPU launch state, then one synchronizer per destination.
    // Abort/link/capture must share the SAME destination state: independent
    // complement chains can disagree for a destination edge. Reset is closed.
    // CPU admission is immediate; ingress epoch reset uses the media controller's registered qualification.
    val mediaOpen = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        RegNext(media.io.linkUp, false.B)
    }
    val txLink = ManagedPeripheralSupport.level(mediaOpen, txManaged, txRelease.resetOut)
    val rxLink = ManagedPeripheralSupport.level(mediaOpen, rxManaged, rxRelease.resetOut)
    val rawRxOpen = ManagedPeripheralSupport.level(mediaOpen, rawRxClock, rawRxRelease.resetOut)
    val txAbort = !txLink
    val rxAbort = !rxLink
    val rawRxAbort = !rawRxOpen
    decode.io.abort := rawRxAbort
    decode.io.admissionClosed := rawRxAbort
    decode.io.rise := rawRgmiiRxRise
    decode.io.fall := rawRgmiiRxFall
    val physicalIngress = Module(new EthernetPhysicalIngress(64))
    physicalIngress.sourceClock := rawRxClock
    physicalIngress.destinationClock := continuousTxClock
    physicalIngress.commonReset := (commonReset.asBool || media.io.ingressReset).asAsyncReset
    physicalIngress.sourceData := decode.io.gmiiData
    physicalIngress.sourceValid := decode.io.gmiiValid
    physicalIngress.sourceError := decode.io.gmiiError
    physicalIngress.sourceByteStep := decode.io.byteStep
    physicalIngress.physicalValid := rawRgmiiRxRise(4)
    physicalIngress.captureEnable := rawRxOpen
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
    val runtimeRxStop = runtimeAdmissionPort.map(_.rxStopRequest).getOrElse(false.B)
    val runtimeTxStop = runtimeAdmissionPort.map(_.txStopRequest).getOrElse(false.B)
    adapter.io.stopNewTx.get := txQ || txIso || media.io.stopNewTraffic || runtimeTxStop
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
    // Default-off timing boundary: RX gains one managed edge; TX keeps the
    // encoder's original byte epoch. Both source samples run while gates stop.
    val rawHandoff = if (rawClockHandoff) Some(Module(new MacRawHandoff)) else None
    rawHandoff.foreach { handoff =>
        // Sample on the same continuous leaf as the encoder, ingress and reset release.
        handoff.rawClock := continuousTxClock
        handoff.rawReset := rawTxRelease.resetOut
        handoff.rxClock := rxManaged
        handoff.rxReset := rxRelease.resetOut
        handoff.rawTxByteStep := encode.io.byteStep
    }
    tx.io.byteStep.get := rawHandoff.map(_.txByteStep).getOrElse(encode.io.byteStep)
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
    txStats.delta.ready := (if (runtimeControlPark) !parkControl else true.B)
    rxStats.delta.ready := (if (runtimeControlPark) !parkControl else true.B)
    val rxDiagnostics = Module(new CdcCounterBank(8))
    rxDiagnostics.sourceClock := rxManaged
    rxDiagnostics.destinationClock := sourceClock
    rxDiagnostics.commonReset := commonReset
    for (n <- 0 until 8) rxDiagnostics.increment(n) := rx.io.dropReasons.get(n)
    rxDiagnostics.delta.ready := (if (runtimeControlPark) !parkControl else true.B)
    val rawDiagnostics = Module(new CdcCounterBank(3))
    rawDiagnostics.sourceClock := rawRxClock
    rawDiagnostics.destinationClock := sourceClock
    rawDiagnostics.commonReset := commonReset
    rawDiagnostics.increment(0) := decode.io.oddNibble
    rawDiagnostics.increment(1) := physicalIngress.wholeFrameSkipped
    rawDiagnostics.increment(2) := physicalIngress.overflow
    rawDiagnostics.delta.ready := (if (runtimeControlPark) !parkControl else true.B)
    val tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)
    val config = GmacParams(controlClockHz = cpuHz, mdcHz = 1250000, aggregateStats = true, rxAdmissionStop = true,
        maxFrameBytes = networkDmaConfig.maxFrameBytes, rxFrameSlots = networkDmaConfig.macRxSlots,
        triSpeedExtensions = true, externalMdio = true)
    val frontend = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(new RegisterGmacControl(config.base, tlParams, runtimeObservation = runtimeControlPark))
    }
    val csr = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(new TileLinkGmacControl(config, tlParams))
    }
    if (runtimeControlPark) {
        // An offer visible before park remains irrevocable until accepted.
        // New requests on the park edge stay upstream; accepted replies drain.
        val offered = withClockAndReset(sourceClock, cpuRelease.resetOut) { RegInit(false.B) }
        val offeredBits = withClockAndReset(sourceClock, cpuRelease.resetOut) {
            Reg(chiselTypeOf(registers.request.bits))
        }
        val allowed = !parkControl || offered
        frontend.io.registers.request.valid := registers.request.valid && allowed
        frontend.io.registers.request.bits := registers.request.bits
        registers.request.ready := frontend.io.registers.request.ready && allowed
        registers.response <> frontend.io.registers.response
        withClockAndReset(sourceClock, cpuRelease.resetOut) {
            when(frontend.io.registers.request.valid) {
                offered := !frontend.io.registers.request.ready
                when(!frontend.io.registers.request.ready) { offeredBits := registers.request.bits }
            }
            assert(!offered || (registers.request.valid && registers.request.bits.asUInt === offeredBits.asUInt),
                "park upstream changed a previously offered CSR request")
        }
        controlPark.get.csrDrained := !offered && frontend.io.runtimeIdle.get && !frontend.io.registers.request.fire
    } else {
        frontend.io.registers <> registers
    }
    csr.io.tl <> frontend.io.tl
    val port = csr.io.ports.head
    // Conservative 400 ns read half-cycle includes the two-FF pad synchronizer
    // and RTL8211F MDIO response delay. mdioIn is the raw IOBUF input here.
    val mdio = withClockAndReset(sourceClock, cpuRelease.resetOut) { Module(new MdioClause22(cpuHz, 1250000)) }
    val mdioOwner = withClockAndReset(sourceClock, cpuRelease.resetOut) { Module(new ManagedMdioArbiter(runtimeObservation = runtimeControlPark)) }
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
    rxStop.requested := port.rxStopRequest.get || media.io.stopNewTraffic || runtimeRxStop
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
    // Synchronize this AON request once in the always-running raw parent.
    // Independent raw/managed synchronizers can observe different request epochs.
    // The managed ACK still requires two actual managed edges and its ACK stage;
    // all raw-to-managed paths remain timed by their proved fixed125 clock family.
    val rxQuiesceRaw = ManagedPeripheralSupport.level(control(1).quiesce,
        continuousTxClock, rawTxRelease.resetOut)
    val ingress = Module(new PeripheralWakeDelay(11,
        ManagedPeripheralSupport.wakeDelay(mediaHz, cpuHz, aonHz), synchronousQuiesce = true))
    ingress.rawClock := continuousTxClock
    ingress.commonReset := commonReset
    ingress.payload := Cat(physicalIngress.byteStep, physicalIngress.valid, physicalIngress.error, physicalIngress.data)
    ingress.active := physicalIngress.valid
    ingress.quiesce := rxQuiesceRaw
    ingress.isolate := control(1).isolate
    rawHandoff.foreach { handoff => handoff.rawRxPayload := ingress.delayed }
    val rxIngressPayload = rawHandoff.map(_.rxPayload).getOrElse(ingress.delayed)
    // Valid denotes pending capture work; idle byteStep/data residue is not an
    // occupied stream slot. Existing ingress.empty and parser owners still apply.
    val rxIngressPending = rawHandoff.map(_.rxPending).getOrElse(false.B)
    rx.io.gmiiData := rxIngressPayload(7, 0)
    rx.io.gmiiError := rxIngressPayload(8)
    rx.io.gmiiValid := rxIngressPayload(9)
    rx.io.byteStep.get := rxIngressPayload(10)
    // Launch these return levels from fixed raw TX, which keeps running when
    // recovered RXC or either managed gate stops. A sample delays both polarities;
    // owner/admission handshakes, not this delay alone, establish safe draining.
    val ingressEmptySource = withClockAndReset(continuousTxClock, rawTxRelease.resetOut) {
        RegNext(ingress.empty, false.B)
    }
    // txManaged is a phase-related gated derivative of rawTxClock. Keep these
    // source-to-register paths timed; they are not asynchronous false paths.
    val txWireDrainedSource = withClockAndReset(continuousTxClock, rawTxRelease.resetOut) {
        RegNext(!tx.io.busy && txFifo.destinationIdle && encode.io.idle, false.B)
    }
    val ingressEmpty = ManagedPeripheralSupport.level(ingressEmptySource, sourceClock, cpuRelease.resetOut)
    val txWireDrained = ManagedPeripheralSupport.level(txWireDrainedSource, sourceClock, cpuRelease.resetOut)
    media.io.txDrained := adapter.io.txIdle && txFifo.sourceIdle && txWireDrained
    media.io.rxDrained := rxStop.drained && ingressEmpty
    txIdle := media.io.txDrained
    rxDrained := media.io.rxDrained
    runtimeAdmissionPort.foreach { admission =>
        // Physical traffic can continue to drain/drop after admitted owners retire.
        // Do not couple fabric admission to the stronger media/clock-gating ACK.
        admission.rxDrained := rxStop.drained
        admission.txDrained := media.io.txDrained
        // Releasing the runtime votes never overrides an independent software or
        // media stop; settled proves the resulting shared RX command has retired.
        admission.released := !runtimeRxStop && !runtimeTxStop && rxStop.settled
    }
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
        !rxConfig.destination.valid && ingress.empty && !rxIngressPending && rxDiagnostics.sourceIdle
    for ((domainClock, n) <- Seq(txManaged, rxManaged).zipWithIndex) {
        val agent = Module(new PeripheralQuiesceAck(synchronousQuiesce = n == 1))
        agent.domainClock := domainClock
        agent.commonReset := commonReset
        agent.quiesce := (if (n == 1) rxQuiesceRaw else control(n).quiesce)
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
    val txDelta = Mux((if (runtimeControlPark) txStats.delta.fire else txStats.delta.valid), txStats.delta.bits.asUInt, 0.U).asTypeOf(Vec(5, UInt(32.W)))
    val rxDelta = Mux((if (runtimeControlPark) rxStats.delta.fire else rxStats.delta.valid), rxStats.delta.bits.asUInt, 0.U).asTypeOf(Vec(5, UInt(32.W)))
    val rawDelta = Mux((if (runtimeControlPark) rawDiagnostics.delta.fire else rawDiagnostics.delta.valid), rawDiagnostics.delta.bits.asUInt, 0.U)
        .asTypeOf(Vec(3, UInt(32.W)))
    val totalDrops = rxDelta(1) + rawDelta(1)
    port.deltas.get := VecInit(Seq(txDelta(0), rxDelta(0), totalDrops, rxDelta(2), txDelta(2), rxDelta(3)))
    port.events := Cat(port.linkUp =/= previousLink, txDelta(1).orR, rxDelta(2).orR,
        totalDrops.orR, rxDelta(0).orR, txDelta(0).orR)
    port.txBytes := 0.U
    port.rxBytes := 0.U
    val diagnosticDelta = Mux((if (runtimeControlPark) rxDiagnostics.delta.fire else rxDiagnostics.delta.valid), rxDiagnostics.delta.bits.asUInt, 0.U)
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
    controlPark.foreach { p =>
        p.released := withClockAndReset(sourceClock, cpuRelease.resetOut) { RegNext(!p.request, false.B) }
        p.configDrained := !configPending
        p.mdioDrained := !mdio.io.busy && mdioOwner.io.runtimeIdle.get
        p.phyParked := phy.io.parked.get
        p.phyFault := phy.io.fault
        p.mediaSettled := !media.io.pending
        p.statisticsPending := Cat(!rawDiagnostics.destinationIdle, !rxDiagnostics.destinationIdle,
            !rxStats.destinationIdle, !txStats.destinationIdle)
        p.parked := p.request && p.csrDrained && p.configDrained && p.mdioDrained &&
            p.phyParked && p.mediaSettled
    }
    irq := csr.io.irq.orR
}
