package ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.TLParams
import soc.core.ooo.FpgaNextConfig
import soc.ip.bus.RegisterPort
import soc.ip.ethernet._

/** The service inputs are already-synchronized CPU-domain observations of
  * omitted media/CDC endpoints. They are never clocks, raw RGMII symbols, or
  * an assertion of physical timing equivalence. Scalar fields keep GSIM's ABI.
  */
class MatchingGmacService extends Bundle {
    val txFrame = Decoupled(new EthernetFrameBeat(4))
    val rxFrame = Flipped(Decoupled(new EthernetFrameBeat(4)))
    val txConfig = Decoupled(new EthernetConfigSnapshot)
    val rxConfig = Decoupled(new EthernetConfigSnapshot)
    val txConfigIdle = Input(Bool())
    val rxConfigIdle = Input(Bool())
    val txRate = Decoupled(UInt(2.W))
    val rxRate = Decoupled(UInt(2.W))
    val txRateIdle = Input(Bool())
    val rxRateIdle = Input(Bool())
    val rxStop = Decoupled(Bool())
    val rxStopIdle = Input(Bool())
    val txFrameSourceIdle = Input(Bool())
    val rxFrameDestinationIdle = Input(Bool())
    val txMediaBusy = Input(Bool())
    val rxMediaBusy = Input(Bool())
    val txWireDrained = Input(Bool())
    val ingressEmpty = Input(Bool())
    val ingressReady = Input(Bool())
    val rxClockPresent = Input(Bool())
    val receiverWake = Input(Bool())
    val txQuiesce = Input(Bool())
    val txIsolate = Input(Bool())
    val rxQuiesce = Input(Bool())
    val txStatsIdle = Input(Bool())
    val rxStatsIdle = Input(Bool())
    val rxDiagnosticsIdle = Input(Bool())
    val txWake = Output(Bool())
    val rxWake = Output(Bool())
    val txDrainCpu = Output(Bool())
    val rxDrainCpu = Output(Bool())
    val ingressReset = Output(Bool())
    val abortTraffic = Output(Bool())
    val linkUp = Output(Bool())
    val mediaPending = Output(Bool())
    val appliedSpeed = Output(UInt(2.W))
    val phyInitialized = Output(Bool())
    val phyPollCount = Output(UInt(32.W))
    val txIdle = Output(Bool())
    val rxIdle = Output(Bool())
    // Atomic modulo-32 CPU-visible delta snapshots; host pulses once per image.
    val txFrames = Input(UInt(32.W))
    val txRejected = Input(UInt(32.W))
    val txBytes = Input(UInt(32.W))
    val rxFrames = Input(UInt(32.W))
    val rxDrops = Input(UInt(32.W))
    val rxBadFcs = Input(UInt(32.W))
    val rxBytes = Input(UInt(32.W))
    val diagnostic0 = Input(UInt(32.W))
    val diagnostic1 = Input(UInt(32.W))
    val diagnostic2 = Input(UInt(32.W))
    val diagnostic3 = Input(UInt(32.W))
    val diagnostic4 = Input(UInt(32.W))
    val diagnostic5 = Input(UInt(32.W))
    val diagnostic6 = Input(UInt(32.W))
    val diagnostic7 = Input(UInt(32.W))
    val diagnostic8 = Input(UInt(32.W))
    val diagnostic9 = Input(UInt(32.W))
    val diagnostic10 = Input(UInt(32.W))
    val diagnostic11 = Input(UInt(32.W))
    val diagnostic12 = Input(UInt(32.W))
    val diagnostic13 = Input(UInt(32.W))
    // PHY pad service. Real CPU-domain MDIO engine/arbitration/policy remain.
    val mdioIn = Input(Bool())
    val mdc = Output(Bool())
    val mdioOut = Output(Bool())
    val mdioOe = Output(Bool())
}

/** Retains the exact CPU-domain modules/parameters from TriSpeedManagedGmac.
  * Peripheral-domain MAC engines, pin adaptation, CDC mailboxes/FIFOs/counters,
  * physical reset synchronizers and managed gates are modeled at their CPU-side
  * transaction/level boundaries. Only this composition glue is test-specific.
  */
class MatchingGmacCpu(config: FpgaNextConfig) extends Module {
    require(config.experimentalTriSpeedEthernet && config.triSpeedTxFrameSlots == 2)
    val io = IO(new Bundle {
        val registers = Flipped(new RegisterPort)
        val streams = new ManagedGmacStreams
        val service = new MatchingGmacService
        val irq = Output(Bool())
    })
    val service = io.service
    val phy = Module(new Rtl8211fPhyManager(config.cpuHz,
        startupCycles = config.cpuHz / 20, pollCycles = config.cpuHz / 10))
    val media = Module(new EthernetMediaTransition(config.cpuHz / 2))
    val adapter = Module(new EthernetDmaFrameAdapter(managed = true))
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)
    val csrConfig = GmacParams(controlClockHz = config.cpuHz, mdcHz = 1250000,
        aggregateStats = true, rxAdmissionStop = true,
        maxFrameBytes = config.network.maxFrameBytes, rxFrameSlots = config.network.macRxSlots,
        triSpeedExtensions = true, externalMdio = true)
    val frontend = Module(new RegisterGmacControl(csrConfig.base, params))
    val csr = Module(new TileLinkGmacControl(csrConfig, params))
    val mdio = Module(new MdioClause22(config.cpuHz, 1250000))
    val mdioOwner = Module(new ManagedMdioArbiter)
    frontend.io.registers <> io.registers
    csr.io.tl <> frontend.io.tl
    val port = csr.io.ports.head
    adapter.io.txData <> io.streams.txData
    adapter.io.txControl <> io.streams.txControl
    io.streams.rxData <> adapter.io.rxData
    io.streams.rxStatus <> adapter.io.rxStatus
    service.txFrame <> adapter.io.txFrame
    adapter.io.rxFrame <> service.rxFrame
    adapter.io.stopNewTx.get := service.txQuiesce || service.txIsolate || media.io.stopNewTraffic
    service.txIdle := adapter.io.txIdle
    service.rxIdle := adapter.io.rxIdle

    // Original CPU-domain PHY/MDIO ownership, including exclusive page lock.
    mdioOwner.io.policyCommand <> phy.io.command
    phy.io.response <> mdioOwner.io.policyResponse
    mdioOwner.io.policyLock := phy.io.lock
    mdioOwner.io.initialized := phy.io.initialized
    mdioOwner.io.softwareCommand <> port.mdioCommand.get
    port.mdioResponse.get <> mdioOwner.io.softwareResponse
    mdio.io.command <> mdioOwner.io.engineCommand
    mdioOwner.io.engineResponse <> mdio.io.response
    // CdcLevel on the MDIO pad has two source-clock stages; synchronous reset
    // replaces asynchronous reset assertion, not the sampling latency.
    val mdioMeta = RegNext(service.mdioIn, false.B)
    mdio.io.mdioIn := RegNext(mdioMeta, false.B)
    service.mdc := mdio.io.mdc
    service.mdioOut := mdio.io.mdioOut
    service.mdioOe := mdio.io.mdioOe
    phy.io.restart := port.restartPhy.get

    // Original source-domain RX admission ownership. Only the complete mailbox
    // is replaced; host ACK must mean the destination actually drained/consumed.
    val stopRequested = port.rxStopRequest.get || media.io.stopNewTraffic
    val stopSent = RegInit(false.B)
    val stopDirty = stopRequested =/= stopSent
    service.rxStop.valid := stopDirty
    service.rxStop.bits := stopRequested
    when(service.rxStop.fire) { stopSent := stopRequested }
    val stopSettled = !stopDirty && service.rxStopIdle
    val stopDrained = stopRequested && stopSettled && adapter.io.rxIdle && service.rxFrameDestinationIdle
    port.rxStopDrained.get := stopDrained

    media.io.requestedLink := phy.io.linkUp && service.rxClockPresent
    media.io.requestedSpeed := phy.io.requestedSpeed
    service.txRate <> media.io.txRate
    service.rxRate <> media.io.rxRate
    media.io.txRateIdle := service.txRateIdle
    media.io.rxRateIdle := service.rxRateIdle
    media.io.ingressReady := service.ingressReady
    media.io.txDrained := adapter.io.txIdle && service.txFrameSourceIdle && service.txWireDrained
    media.io.rxDrained := stopDrained && service.ingressEmpty
    service.ingressReset := media.io.ingressReset
    service.abortTraffic := media.io.abortTraffic
    service.linkUp := media.io.linkUp
    service.mediaPending := media.io.pending
    service.appliedSpeed := media.io.appliedSpeed
    service.phyInitialized := phy.io.initialized
    service.phyPollCount := phy.io.pollCount

    val currentConfig = Wire(new EthernetConfigSnapshot)
    currentConfig.macAddress := port.macAddress
    currentConfig.txEnable := port.txEnable
    currentConfig.rxEnable := port.rxEnable
    currentConfig.promiscuous := port.promiscuous
    currentConfig.broadcastEnable := port.broadcastEnable
    val sentConfig = RegInit(0.U(52.W))
    val dirty = currentConfig.asUInt =/= sentConfig
    service.txConfig.valid := dirty && service.rxConfig.ready
    service.rxConfig.valid := dirty && service.txConfig.ready
    service.txConfig.bits := currentConfig
    service.rxConfig.bits := currentConfig
    when(service.txConfig.fire && service.rxConfig.fire) { sentConfig := currentConfig.asUInt }
    val configPending = dirty || !service.txConfigIdle || !service.rxConfigIdle
    port.linkUp := media.io.linkUp
    val previousLink = RegNext(port.linkUp, false.B)
    port.txBusy := service.txMediaBusy || !adapter.io.txIdle || !service.txFrameSourceIdle || configPending
    port.rxBusy := service.rxMediaBusy || configPending || !stopSettled || (port.rxStopRequest.get && !stopDrained)
    port.deltas.get := VecInit(Seq(service.txFrames, service.rxFrames, service.rxDrops,
        service.rxBadFcs, service.txBytes, service.rxBytes))
    port.events := Cat(port.linkUp =/= previousLink, service.txRejected.orR, service.rxBadFcs.orR,
        service.rxDrops.orR, service.rxFrames.orR, service.txFrames.orR)
    port.txBytes := 0.U
    port.rxBytes := 0.U
    port.diagnosticDeltas.get := VecInit(Seq(service.diagnostic0, service.diagnostic1,
        service.diagnostic2, service.diagnostic3, service.diagnostic4, service.diagnostic5,
        service.diagnostic6, service.diagnostic7, service.diagnostic8, service.diagnostic9,
        service.diagnostic10, service.diagnostic11, service.diagnostic12, service.diagnostic13))
    port.mediaStatus.get := (BigInt(1) << 56).U(64.W) |
        Cat(service.rxClockPresent, media.io.rxDrained, media.io.txDrained, media.io.linkUp, phy.io.fault,
            media.io.timedOut, media.io.pending, media.io.appliedSpeed, phy.io.requestedSpeed,
            phy.io.linkUp, phy.io.initialized)
    port.phyCounters.get(0) := Cat(phy.io.verifyErrorCount, phy.io.noAckCount)
    port.phyCounters.get(1) := Cat(phy.io.pollCount, phy.io.linkChangeCount)
    port.phyCounters.get(2) := Cat(media.io.timeoutCount, phy.io.unsupportedCount)
    port.mdioIn := true.B
    service.txWake := RegNext(dirty || media.io.pending || ((service.txQuiesce || service.txIsolate) &&
        (io.streams.txData.valid || io.streams.txControl.valid)), false.B)
    service.rxWake := RegNext(dirty || media.io.pending || service.receiverWake || !stopSettled, false.B)
    service.txDrainCpu := RegNext(service.txQuiesce && adapter.io.txIdle && service.txFrameSourceIdle &&
        service.txConfigIdle && !dirty && service.txStatsIdle, false.B)
    service.rxDrainCpu := RegNext(service.rxQuiesce && adapter.io.rxIdle && service.rxFrameDestinationIdle &&
        service.rxConfigIdle && !dirty && service.rxStatsIdle && service.rxDiagnosticsIdle && stopSettled, false.B)
    io.irq := csr.io.irq.orR
}
