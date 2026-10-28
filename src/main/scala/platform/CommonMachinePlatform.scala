package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.axi.{Axi4ClockDomainBoundary, Axi4MemoryPort}
import soc.ip.bus.{CdcLevel, CdcResetRelease, ResetDistributionDriver}
import soc.ip.clock.{ClockRateAdmission, ClockRateBackendPort, ClockRateParams, ClockRatePoint, ClockPerformanceTelemetry, ManagedPeripheralBank}
import soc.ip.debug.{DebugDmiClockBoundary, DebugDmiPort}
import soc.ip.timer.FixedTimebaseBoundary

class CommonRetireTrace extends Bundle {
    val pc = UInt(64.W)
    val instruction = UInt(32.W)
    val nextPc = UInt(64.W)
    val rd = UInt(5.W)
    val writesRd = Bool()
    val data = UInt(64.W)
}

/** Explicit AON isolation-test endpoint. No rate backend or full-system gate ACK. */
class CommonPlatformRuntimePort(p: CommonCpuTilePortParams) extends Bundle {
    val requests = Vec(2, Flipped(Decoupled(UInt(32.W))))
    val resume = Vec(2, Flipped(Decoupled(new CommonRuntimeAonStatus(p))))
    val cancel = Vec(2, Flipped(Decoupled(new CommonRuntimeAonStatus(p))))
    val held = Output(Vec(2, Valid(new CommonRuntimeAonStatus(p))))
    val result = Vec(2, Decoupled(new CommonRuntimeAonResult(p)))
    val busy = Output(Bool())
    val cleanupFault = Output(Bool())
    val debugFault = Output(Bool())
    val timeoutSelected = Output(Bool())
}

/** One public platform, selected CPU-private tile, static independent clocks.
  * DDR AXI belongs to fabricClock; the initial target uses the same 250 MHz UI
  * clock by default. independentDdrClock inserts a complete five-channel AXI
  * crossing to the separately supplied fixed DDR UI clock; board CDC/STA signoff
  * remains required before enabling that configuration. All raw/CPU/fabric clocks must remain running.
  * This is a native tri-speed RGMII-edge/DMI/AXI assembly, not an FPGA pin/MMCM/MIG wrapper.
  */
class CommonMachinePlatform(
    val profile: CommonCpuProfile,
    romFiles: Seq[String] = Seq.empty,
    programmable: Boolean = false,
    hardwareClocks: Boolean = true,
    vivadoMemories: Boolean = false,
    independentDdrClock: Boolean = false,
    independentTimebaseClock: Boolean = false,
    independentDebugClock: Boolean = false,
    runtimeDebugAdmission: Boolean = false,
    runtimeNetworkAdmission: Boolean = false,
    runtimeFixedQualification: Boolean = false,
    runtimeControlQualification: Boolean = false,
    runtimeFixedMac: Boolean = false,
    runtimeRateControl: Boolean = false,
    externalIrqsAbsent: Boolean = false,
    testOnlyRateParams: Option[Seq[ClockRateParams]] = None,
    diagnosticRateAdmission: Boolean = false,
    performanceTelemetry: Boolean = false,
    telemetryWindowCycles: Int = 50000,
    experimentalA1Runtime: Boolean = false,
    val a1Experimental: Option[CommonA1ExperimentalSelection] = None,
    val peripheralConfig: CommonPeripheralConfig = CommonPeripheralConfig()
) extends RawModule {
    peripheralConfig.validateRuntime(runtimeDebugAdmission)
    require(!experimentalA1Runtime || (profile == CommonCpuProfile.A1Boot50 &&
        runtimeRateControl && performanceTelemetry && independentDebugClock && independentDdrClock &&
        independentTimebaseClock && runtimeNetworkAdmission && runtimeFixedQualification &&
        runtimeControlQualification && runtimeFixedMac),
        "experimental A1 runtime requires boot50 and the complete fixed/debug/network/rate/telemetry chain")
    require(!runtimeDebugAdmission || ((profile.kind == "i1" || experimentalA1Runtime) && independentDebugClock),
        "runtime debug isolation requires a qualified I1 or explicitly experimental complete A1 endpoint")
    require(!runtimeNetworkAdmission || runtimeDebugAdmission,
        "network runtime ordering requires the opt-in debug and real tile epoch path")
    require(!runtimeFixedQualification ||
        (runtimeDebugAdmission && independentDdrClock && independentTimebaseClock),
        "fixed-domain runtime proof requires the real tile epoch path and real DDR/timer boundaries")
    require(!runtimeControlQualification || (runtimeFixedQualification && runtimeNetworkAdmission),
        "managed control qualification requires the real network and fixed-domain epoch joins")
    require(!runtimeFixedMac || runtimeControlQualification,
        "fixed MAC integration requires the complete existing control/network/fixed epoch path")
    require(!runtimeRateControl || (runtimeFixedMac && !programmable),
        "dynamic rate integration needs all real owners and no unhandshaked ROM programming source")
    require(!performanceTelemetry || runtimeRateControl)
    require(testOnlyRateParams.isEmpty || runtimeRateControl)
    require(!diagnosticRateAdmission || (runtimeRateControl && testOnlyRateParams.isEmpty &&
        profile.clockProfile == "boot50-dynamic"), "diagnostic rates require the explicit real dynamic platform")
    val configuredRateDomains: Seq[ClockRateParams] = testOnlyRateParams.getOrElse(
        if (diagnosticRateAdmission) CommonDiagnosticRateProfile.domains
        else if (runtimeRateControl) Seq(ClockRateParams(maximumHz = 300000000L),
            ClockRateParams(maximumHz = 250000000L))
        else Seq(ClockRateParams(), ClockRateParams(maximumHz = 150000000L)))
    require(profile.clockProfile != "boot50-dynamic" || runtimeRateControl)
    private val boundary = if (runtimeDebugAdmission) profile.boundary.copy(
        runtimeMaintenance = true, runtimeCancellation = true, runtimeInterruptHold = true) else profile.boundary
    CommonA1ExperimentalSelection.validate(profile, a1Experimental, boundary, experimentalA1Runtime)
    val a1CpuConfig = CommonA1ExperimentalSelection.config(profile, a1Experimental)
    val a1MemoryProfile = CommonA1ExperimentalSelection.memoryProfile(a1Experimental)
    require(independentDdrClock || profile.fabricHz == profile.ddrUiHz,
        "a fabric frequency different from fixed DDR UI requires the complete AXI boundary")
    require(independentTimebaseClock || profile.fabricHz == profile.clocks.timebaseHz,
        "a fabric frequency different from fixed timebase requires the timer boundary")
    require(!profile.independentFixedDomains ||
        (independentDdrClock && independentTimebaseClock && independentDebugClock),
        "the independent fixed-domain profile requires DDR, timer and DMI boundaries even at equal rates")
    val rateBackend = if (runtimeRateControl) Some(IO(Vec(2, new ClockRateBackendPort))) else None
    private val rateFatal = if (runtimeRateControl) Some(Wire(Bool())) else None
    private val fixedDebugFault = if (runtimeRateControl) Some(Wire(Bool())) else None
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val ddrClock = if (independentDdrClock) Some(IO(Input(Clock()))) else None
    val timebaseClock = if (independentTimebaseClock) Some(IO(Input(Clock()))) else None
    val debugClock = if (independentDebugClock) Some(IO(Input(Clock()))) else None
    val rawUartClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        val ddrAxi = new Axi4MemoryPort(32, profile.fpga.ddr.axiIdWidth)
        val ddrReady = Input(Bool())
        // Cold-start admission only; dropping this after startup cannot reset or cancel owners.
        val bootEnable = Input(Bool())
        val sources = Input(UInt(CommonPlatformAbi.interruptSources.W))
        val uartRx = Input(Bool()); val uartTx = Output(Bool())
        val gmiiRxData = Input(UInt(8.W)); val gmiiRxValid = Input(Bool()); val gmiiRxError = Input(Bool())
        val gmiiTxData = Output(UInt(8.W)); val gmiiTxEnable = Output(Bool()); val gmiiTxError = Output(Bool())
        val linkUp = Input(Bool()); val mdc = Output(Bool()); val mdioIn = Input(Bool())
        val triSpeedRgmii = new soc.ip.ethernet.TriSpeedRgmiiPortV1
        val mdioOut = Output(Bool()); val mdioOe = Output(Bool())
        val jtagDmi = if (peripheralConfig.jtagDownload) Some(Flipped(new DebugDmiPort(7))) else None
        val jtagLinkUp = if (peripheralConfig.jtagDownload) Some(Input(Bool())) else None
        val maintenance = Flipped(Decoupled(new CommonTileMaintenanceCommand(boundary)))
        val runtime = if (runtimeDebugAdmission && !runtimeRateControl) Some(new CommonPlatformRuntimePort(boundary)) else None
        val maintenanceStatus = Output(Valid(new CommonTileMaintenanceStatus(boundary)))
        val retire = Output(Vec(2, Valid(new CommonRetireTrace)))
        val trap = Output(Valid(new Bundle { val pc = UInt(64.W); val cause = UInt(64.W) }))
        val cpuCycles = Output(UInt(64.W)); val instructions = Output(UInt(64.W))
        val fabricCycles = Output(UInt(64.W)); val timeSnapshot = Output(UInt(64.W))
        val cpuLinkReady = Output(Bool()); val fabricLinkReady = Output(Bool())
        val cpuTransportEmpty = Output(Bool()); val fabricTransportEmpty = Output(Bool())
        val maintenancePending = Output(Bool()); val homeDrained = Output(Bool())
        val program = if (programmable) Some(Input(Valid(new Bundle {
            val index = UInt(log2Ceil(CommonPlatformAbi.romWords).W); val data = UInt(32.W)
        }))) else None
    })
    private val fabricRelease = Module(new CdcResetRelease)
    fabricRelease.clockIn := fabricClock; fabricRelease.asyncReset := commonColdReset
    // Fixed UI readiness is a level, never an unsynchronized fabric enable.
    private val fabricDdrReady = if (independentDdrClock) {
        val ddrReadySync = Module(new CdcLevel)
        ddrReadySync.clockIn := fabricClock; ddrReadySync.resetIn := fabricRelease.resetOut
        ddrReadySync.levelIn := io.ddrReady
        ddrReadySync.levelOut
    } else io.ddrReady
    private val started = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        val admitted = RegInit(false.B)
        when(io.bootEnable && fabricDdrReady) { admitted := true.B }
        when(admitted) { assert(fabricDdrReady, "DDR readiness lost: platform requires a common cold reset") }
        admitted
    }
    // A startup-only extension of reset. 'started' never falls except on common
    // cold reset, so this cannot become a one-sided warm-reset mechanism.
    private val startupReset = (commonColdReset.asBool || !started).asAsyncReset
    private val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := startupReset
    // Dynamic I1 only: retain the complete three-stage synchronizer, then add a
    // physically replicable functional-reset driver. Normal DFS never resets it.
    private val cpuFunctionalReset = if (runtimeRateControl && profile.kind == "i1") {
        val cpuResetDistribution = Module(new ResetDistributionDriver)
        cpuResetDistribution.clockIn := cpuClock
        cpuResetDistribution.synchronizedReset := cpuRelease.resetOut
        cpuResetDistribution.resetOut
    } else cpuRelease.resetOut
    val crossing = Module(new CommonCpuClockBoundary(boundary, depth = 16))
    crossing.cpuClock := cpuClock; crossing.fabricClock := fabricClock
    crossing.commonColdReset := startupReset

    // Exactly one fabric and one managed peripheral bank, OUTSIDE the CPU choice.
    val fabric = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonMachineFabric(boundary = boundary, fpga = profile.fpga,
            features = peripheralConfig.features, ramBytes = profile.fpga.ddrBytes, externalDdr = true,
            romFiles = romFiles, programmable = programmable, vivadoMemories = vivadoMemories,
            externalTimer = independentTimebaseClock, runtimeDebugAdmission = runtimeDebugAdmission,
            runtimeNetworkAdmission = runtimeNetworkAdmission))
    }
    fabric.io.tile <> crossing.fabric
    fabric.io.transportCpuEmptySynchronized := crossing.cpuEmptyInFabric
    fabric.io.fabricTransportEmpty := crossing.fabricTransportEmpty
    fabric.io.ddrReady.get := fabricDdrReady
    // Qualification only observes a drained epoch. It never closes AXI/MMIO
    // ahead of accepted CPU/Home/DMA owners, and is not a physical gate ACK.
    val ddrQualification = if (runtimeFixedQualification)
        Some(Module(new CommonFixedDomainEpochQualifier(boundary))) else None
    val timerQualification = if (runtimeFixedQualification)
        Some(Module(new CommonFixedDomainEpochQualifier(boundary))) else None
    val controlQualification = if (runtimeControlQualification) Some(withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonControlParkEpochSequencer(boundary))
    }) else None
    val fixedQualifiers = ddrQualification.toSeq ++ timerQualification.toSeq
    val fixedFabricIdle = if (runtimeFixedQualification) Some(Wire(Vec(2, Bool()))) else None
    if (independentDdrClock) {
        val ddrCrossing = Module(new Axi4ClockDomainBoundary(32, profile.fpga.ddr.axiIdWidth))
        ddrCrossing.fabricClock := fabricClock; ddrCrossing.ddrClock := ddrClock.get
        ddrCrossing.commonColdReset := commonColdReset
        ddrCrossing.fabric <> fabric.io.ddrAxi.get
        io.ddrAxi <> ddrCrossing.ddr
        ddrQualification.foreach { q =>
            q.fixedClock := ddrClock.get
            q.localIdle := ddrCrossing.ddrTransportEmpty && !ddrCrossing.ddr.aw.valid &&
                !ddrCrossing.ddr.w.valid && !ddrCrossing.ddr.ar.valid &&
                !ddrCrossing.ddr.b.valid && !ddrCrossing.ddr.r.valid
            q.linkReady := ddrCrossing.ddrLinkReady && io.ddrReady
            fixedFabricIdle.get(0) := ddrCrossing.fabricTransportEmpty && ddrCrossing.fabricLinkReady &&
                !fabric.io.ddrAxi.get.aw.valid && !fabric.io.ddrAxi.get.w.valid && !fabric.io.ddrAxi.get.ar.valid
        }
    } else {
        io.ddrAxi <> fabric.io.ddrAxi.get
    }
    fabric.io.timerTick := true.B
    if (independentTimebaseClock) {
        val fixedTimer = Module(new FixedTimebaseBoundary(runtimeObservation = runtimeFixedQualification))
        fixedTimer.fabricClock := fabricClock; fixedTimer.timebaseClock := timebaseClock.get
        fixedTimer.commonColdReset := commonColdReset
        fixedTimer.registers <> fabric.io.externalTimerRegisters.get
        fabric.io.externalTimerIrq.get := fixedTimer.irq
        fabric.io.externalTimeSnapshot.get := fixedTimer.timeSnapshot
        timerQualification.foreach { q =>
            q.fixedClock := timebaseClock.get
            q.localIdle := fixedTimer.timebaseMmioIdle.get
            q.linkReady := fixedTimer.timebaseReady.get
            fixedFabricIdle.get(1) := fixedTimer.fabricMmioIdle.get && fixedTimer.fabricReady.get
        }
    }
    val runtime = if (runtimeDebugAdmission) Some(Module(new CommonRuntimeEpochBoundary(boundary,
        externalRetirementBarrier = true, externalReleaseInterlock = runtimeRateControl,
        finalCloseCommit = runtimeRateControl))) else None
    runtime.foreach { r =>
        r.aonClock := alwaysOnClock; r.cpuClock := cpuClock; r.fabricClock := fabricClock
        r.commonColdReset := commonColdReset
        io.runtime.foreach { external =>
            r.io.requests <> external.requests; r.io.resume <> external.resume
            r.io.cancel <> external.cancel; external.held := r.io.held
            external.result <> r.io.result; external.busy := r.io.busy
            external.cleanupFault := r.io.cleanupFault
            external.timeoutSelected := r.io.timeoutSelected
        }
        r.io.fabricHeld := fabric.io.runtimeHeld.get
        if (runtimeFixedQualification) {
            r.io.fabricHeld.valid := fabric.io.runtimeHeld.get.valid && fixedFabricIdle.get.asUInt.andR &&
                fixedQualifiers.map(q => q.qualified.valid &&
                    q.qualified.bits === fabric.io.runtimeHeld.get.bits).reduce(_ && _)
            fixedQualifiers.zipWithIndex.foreach { case (q, index) =>
                q.fabricClock := fabricClock; q.commonColdReset := commonColdReset
                q.prepare.valid := fabric.io.externalMaintenance.fire
                q.prepare.bits := fabric.io.externalMaintenance.bits.epoch
                q.fabricHeld := fabric.io.runtimeHeld.get
                q.fabricAllObligationsIdle := fabric.io.allObligationsIdle && fixedFabricIdle.get(index)
                q.completion.valid := r.io.runtimeComplete.valid
                q.completion.bits := r.io.runtimeComplete.bits
                q.terminalConsumedAtAon := r.io.terminalConsumedAtAon.get
                q.terminalRetired := r.io.runtimeComplete.fire
            }
        }
        controlQualification.foreach { q =>
            q.io.prepare.valid := fabric.io.externalMaintenance.fire
            q.io.prepare.bits := fabric.io.externalMaintenance.bits.epoch
            q.io.fabricHeld := fabric.io.runtimeHeld.get
            q.io.fabricAllObligationsIdle := fabric.io.allObligationsIdle
            q.io.completion.valid := r.io.runtimeComplete.valid
            q.io.completion.bits := r.io.runtimeComplete.bits
            q.io.terminalConsumedAtAon := r.io.terminalConsumedAtAon.get
            q.io.retired := r.io.runtimeComplete.fire
            // The old CPU/Home/MMIO owners have already drained before control
            // admission parks. This additional qualification never fabricates
            // a clock-gate witness or substitutes for the other drain classes.
            r.io.fabricHeld.valid := fabric.io.runtimeHeld.get.valid && fixedFabricIdle.get.asUInt.andR &&
                fixedQualifiers.map(f => f.qualified.valid &&
                    f.qualified.bits === fabric.io.runtimeHeld.get.bits).reduce(_ && _) &&
                q.io.qualified.valid && q.io.qualified.bits === fabric.io.runtimeHeld.get.bits
        }
        r.io.cpuLinkReady := crossing.cpuLinkReady; r.io.cpuTransportEmpty := crossing.cpuTransportEmpty
        r.io.fabricEmptyInCpu := crossing.fabricEmptyInCpu
        r.io.fabricLinkReady := crossing.fabricLinkReady; r.io.fabricTransportEmpty := crossing.fabricTransportEmpty
        r.io.cpuEmptyInFabric := crossing.cpuEmptyInFabric
        r.io.fabricAllObligationsIdle := fabric.io.allObligationsIdle
        fabric.io.runtimeResume.get <> r.io.runtimeResume
        fabric.io.runtimeCancel.get <> r.io.runtimeCancel
        // No second independent maintenance owner may bypass admission ordering.
        io.maintenance.ready := false.B
    }
    val networkSequence = if (runtimeNetworkAdmission) Some(withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonNetworkRuntimeSequencer(boundary))
    }) else None
    networkSequence.foreach { n =>
        n.io.upstreamPrepare <> runtime.get.io.externalMaintenance
        fabric.io.networkPause.get := n.io.dmaPause
        n.io.dmaTxIdle := fabric.io.networkTxIdle.get
        n.io.dmaOwnersIdle := fabric.io.networkOwnersIdle.get
        fabric.io.networkAdmissionHeld.get := n.io.held
        n.io.terminalConsumedAtAon := runtime.get.io.terminalConsumedAtAon.get
        n.io.retired := runtime.get.io.runtimeComplete.fire
    }
    val fixedMacSequence = if (runtimeFixedMac) Some(withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonFixedMacRuntimeAdapter(boundary))
    }) else None
    fixedMacSequence.foreach { a =>
        val n = networkSequence.get
        a.io.owner.valid := n.io.busy
        a.io.owner.bits := n.io.held.bits
        a.io.rxStop := n.io.rxStop
        a.io.txStop := n.io.txStop
        a.io.park := controlQualification.get.io.parkRequest
        a.io.txProducersClosed := n.io.dmaPause && fabric.io.networkTxIdle.get &&
            !fabric.io.ethernetStreams.get.txData.valid && !fabric.io.ethernetStreams.get.txControl.valid
        a.io.controlProducersClosed := fabric.io.runtimeHeld.get.valid &&
            fabric.io.runtimeHeld.get.bits === n.io.held.bits && fabric.io.allObligationsIdle &&
            !fabric.io.ethernetRegisters.get.request.valid
        a.io.terminalConsumedAtAon := runtime.get.io.terminalConsumedAtAon.get
        a.io.retired := runtime.get.io.runtimeComplete.fire
    }
    if (!runtimeDebugAdmission) fabric.io.externalMaintenance <> io.maintenance
    io.maintenanceStatus := fabric.io.externalMaintenanceStatus
    if (runtimeDebugAdmission) {
        val debugSequence = Module(new CommonDebugRuntimeSequencer(boundary,
            emergencyAdmissionStop = runtimeRateControl))
        if (runtimeRateControl) {
            debugSequence.emergencyStop.get := rateFatal.get
            fixedDebugFault.get := debugSequence.fixedFault.get
        }
        debugSequence.fabricClock := fabricClock; debugSequence.debugClock := debugClock.get
        debugSequence.commonColdReset := commonColdReset
        debugSequence.source <> io.jtagDmi.get; fabric.io.jtagDmi.get <> debugSequence.destination
        debugSequence.sourceLinkUp := io.jtagLinkUp.get
        fabric.io.jtagLinkUp.get := debugSequence.destinationLinkUp
        debugSequence.destinationOwnersIdle := fabric.io.debugDmiOwnersIdle.get
        if (runtimeNetworkAdmission) debugSequence.upstreamPrepare <> networkSequence.get.io.downstreamPrepare
        else debugSequence.upstreamPrepare <> runtime.get.io.externalMaintenance
        fabric.io.externalMaintenance <> debugSequence.downstreamPrepare
        debugSequence.downstreamComplete <> fabric.io.runtimeComplete.get
        runtime.get.io.runtimeComplete <> debugSequence.upstreamComplete
        debugSequence.terminalConsumedAtAon := runtime.get.io.terminalConsumedAtAon.get
        runtime.get.io.retirementPermit.get := debugSequence.retirementPermit &&
            networkSequence.map(_.io.retirementPermit).getOrElse(true.B) &&
            (if (runtimeFixedQualification) fixedQualifiers.map(_.retirementPermit).reduce(_ && _) else true.B) &&
            controlQualification.map(_.io.retirementPermit).getOrElse(true.B)
        networkSequence.foreach(_.io.fault := debugSequence.fault ||
            fixedMacSequence.map(_.io.fault).getOrElse(false.B))
        runtime.get.io.retirementFault.get := debugSequence.fault ||
            (if (runtimeFixedQualification) fixedQualifiers.map(_.fault).reduce(_ || _) else false.B) ||
            controlQualification.map(_.io.fault).getOrElse(false.B) ||
            fixedMacSequence.map(_.io.fault).getOrElse(false.B)
        val debugFault = Module(new CdcLevel)
        val aonRelease = Module(new CdcResetRelease)
        aonRelease.clockIn := alwaysOnClock; aonRelease.asyncReset := commonColdReset
        debugFault.clockIn := alwaysOnClock; debugFault.resetIn := aonRelease.resetOut
        debugFault.levelIn := debugSequence.fault
        io.runtime.foreach(_.debugFault := debugFault.levelOut)
    } else if (peripheralConfig.jtagDownload && independentDebugClock) {
        val debugCrossing = Module(new DebugDmiClockBoundary(7))
        debugCrossing.sourceClock := debugClock.get; debugCrossing.destinationClock := fabricClock
        debugCrossing.commonColdReset := commonColdReset
        debugCrossing.source <> io.jtagDmi.get; fabric.io.jtagDmi.get <> debugCrossing.destination
        debugCrossing.sourceLinkUp := io.jtagLinkUp.get
        fabric.io.jtagLinkUp.get := debugCrossing.destinationLinkUp
    } else if (peripheralConfig.jtagDownload) {
        fabric.io.jtagDmi.get <> io.jtagDmi.get
        fabric.io.jtagLinkUp.get := io.jtagLinkUp.get
    }
    fabric.io.program.foreach(_ := io.program.get)
    fabric.io.uartRx := true.B // actual UART is the shared managed bank below
    protected def buildPeripheralBank(): ManagedPeripheralBank =
        new ManagedPeripheralBank(profile.cmu, profile.cpuHz, profile.uartHz,
        profile.uartBaud, hardwareClocks, networkDmaConfig = profile.fpga.network,
        triSpeedEthernet = true, triSpeedTxFrameSlots = 2, runtimeAdmission = runtimeNetworkAdmission,
        runtimeControlPark = runtimeControlQualification, runtimeFixedMac = runtimeFixedMac,
        runtimeRateControl = runtimeRateControl, performanceTelemetry = performanceTelemetry,
        sourceClockHz = profile.fabricHz, rateDomains = Some(configuredRateDomains))
    val peripherals = Module(buildPeripheralBank())
    if (runtimeFixedMac) {
        val a = fixedMacSequence.get
        a.io.boundary <> peripherals.fixedMacRuntime.get
        networkSequence.get.io.macRxDrained := a.io.rxDrained
        networkSequence.get.io.macTxDrained := a.io.txDrained
        networkSequence.get.io.macReleased := a.io.released
        controlQualification.get.io.parked := a.io.parked
        controlQualification.get.io.parkReleased := a.io.released
    } else {
    networkSequence.foreach { n =>
        val mac = peripherals.runtimeAdmissionPort.get
        mac.rxStopRequest := n.io.rxStop; mac.txStopRequest := n.io.txStop
        n.io.macRxDrained := mac.rxDrained; n.io.macTxDrained := mac.txDrained
        n.io.macReleased := mac.released
    }
    controlQualification.foreach { q =>
        val park = peripherals.controlPark.get
        park.request := q.io.parkRequest
        q.io.parked := park.parked
        q.io.parkReleased := park.released
        // PHY fault keeps qualification low; cancellation must still release
        // this pause so the unchanged PHY retry machinery can make progress.
    }
    }
    peripherals.sourceClock := fabricClock; peripherals.alwaysOnClock := alwaysOnClock
    peripherals.rawUartClock := rawUartClock; peripherals.rawTxClock := rawTxClock
    peripherals.rawRxClock := rawRxClock; peripherals.commonReset := commonColdReset
    if (!runtimeRateControl) {
        // Production CMU extension is discoverable, but no clock backend or real
        // CPU/fabric quiesce endpoint is connected yet. Explicit absence rejects
        // every rate write; it must not turn a test ACK into a live clock command.
        peripherals.rateEndpoints.get.foreach { endpoint =>
            endpoint.present := false.B
            endpoint.drainAcks := 0.U
            endpoint.gateClosed := false.B; endpoint.gateOpen := false.B
            endpoint.locked := false.B; endpoint.resumed := false.B
            endpoint.program.ready := false.B
            endpoint.result.valid := false.B
            endpoint.result.bits := 0.U.asTypeOf(endpoint.result.bits)
        }
    } else {
        val r = runtime.get
        r.io.fabricControlOwnersIdle.get := peripherals.runtimeFabricOwnerIdle.get
        r.io.fabricFixedOwnersIdle.get := fixedFabricIdle.get.asUInt.andR &&
            fixedQualifiers.map(q => q.qualified.valid &&
                q.qualified.bits === fabric.io.runtimeHeld.get.bits).reduce(_ && _)
        val aonRelease = Module(new CdcResetRelease)
        aonRelease.clockIn := alwaysOnClock; aonRelease.asyncReset := commonColdReset
        val debugFaultSync = Module(new CdcLevel)
        debugFaultSync.clockIn := alwaysOnClock; debugFaultSync.resetIn := aonRelease.resetOut
        debugFaultSync.levelIn := fixedDebugFault.get
        withClockAndReset(alwaysOnClock, aonRelease.resetOut) {
            val adapter = Module(new CommonClockRateEpochAdapter(boundary))
            adapter.io.clients <> peripherals.rateLeases.get
            r.io.requests <> adapter.io.requests; r.io.resume <> adapter.io.resume
            r.io.cancel <> adapter.io.cancel
            adapter.io.held := r.io.held; adapter.io.result <> r.io.result
            adapter.io.busy := r.io.busy; adapter.io.activeLane := r.io.activeLane
            adapter.io.activeEpoch := r.io.activeEpoch; adapter.io.activeToken := r.io.activeToken
            adapter.io.drainDeadline := r.io.drainDeadline; adapter.io.timeoutSelected := r.io.timeoutSelected
            adapter.io.cleanupFault := r.io.cleanupFault

            val failed = RegInit(false.B)
            // AON-combinational interlock stops a NEW handshake on the same
            // observed-fault edge. Only 'failed', a sticky AON register, launches
            // the independent emergency-stop CDCs into the fixed domains.
            val observedFault = Wire(Bool())
            val unsafe = failed || observedFault
            val safety = peripherals.rateSafety.get
            val backendFault = rateBackend.get.map(_.fatal).reduce(_ || _)
            val owned = RegInit(false.B)
            val epoch = RegInit(0.U(16.W))
            val armSent = RegInit(false.B); val armAck = RegInit(false.B)
            val armed = RegInit(false.B)
            val disarmSent = RegInit(false.B); val disarmAck = RegInit(false.B)
            when(!owned && r.io.busy) {
                owned := true.B; epoch := r.io.activeEpoch
                armSent := false.B; armAck := false.B; armed := false.B
                disarmSent := false.B; disarmAck := false.B
            }
            val sameOwner = owned && r.io.busy && epoch === r.io.activeEpoch
            val selected = r.io.activeLane
            val targetBackend = rateBackend.get(selected)
            val progress = targetBackend.clockEnable && targetBackend.locked &&
                targetBackend.gateOpen && targetBackend.resumed && !unsafe
            val fixedAonSafe = peripherals.runtimeAonControlIdle.get && peripherals.runtimeAonUartRunning.get
            val laneAllowed = selected === 0.U || externalIrqsAbsent.B
            val wantArm = sameOwner && !armSent && r.io.held(selected).valid && r.io.closeProof.get.andR &&
                fixedAonSafe && laneAllowed && !r.io.releasePending.get
            // No new allocator: the sole runtime owner supplies the epoch tag.
            val wantDisarm = sameOwner && armSent && armAck && !disarmSent &&
                r.io.closeUncommitted.get && progress
            safety.command.valid := !unsafe && (wantArm || wantDisarm)
            safety.command.bits.epoch := epoch
            safety.command.bits.enable := !wantDisarm
            when(safety.command.fire) {
                when(safety.command.bits.enable) { armSent := true.B }
                    .otherwise { disarmSent := true.B }
            }
            safety.receipt.ready := !failed
            val receipt = safety.receipt.bits
            val goodArm = sameOwner && receipt.command.epoch === epoch && receipt.command.enable && armSent && !armAck
            val goodDisarm = sameOwner && receipt.command.epoch === epoch && !receipt.command.enable &&
                disarmSent && !disarmAck && !receipt.guarded
            val badReceipt = safety.receipt.valid && !(goodArm || goodDisarm)
            when(safety.receipt.fire && goodArm) { armAck := true.B; armed := receipt.guarded }
            when(safety.receipt.fire && goodDisarm) { disarmAck := true.B }
            val safetyWindow = armed && !disarmAck
            observedFault := backendFault || safety.fault || r.io.closeFault.get || debugFaultSync.levelOut ||
                r.io.cleanupFault || badReceipt || (safetyWindow && !fixedAonSafe)
            when(observedFault) { failed := true.B }
            when(owned && !r.io.busy) {
                when(armSent && !disarmAck) { failed := true.B }
                owned := false.B
            }
            rateFatal.get := failed
            peripherals.rateBackendFault.get := Fill(2, unsafe)
            peripherals.rateEmergencyStop.get := failed
            // First consume source-owner close proofs, so an initially idle
            // AON receipt destination cannot hide an old in-flight MMIO reply.
            // Actual gate ACK additionally waits fixed safety arm consumption.
            r.io.closeRequest.get := sameOwner && !disarmSent && fixedAonSafe && laneAllowed && !unsafe
            r.io.releasePermit.get := progress
            r.io.finalReleasePermit.get := !unsafe && (!armSent || disarmAck)
            for (i <- 0 until 2) {
                val endpoint = peripherals.rateEndpoints.get(i)
                val backend = rateBackend.get(i)
                endpoint.present := backend.present
                endpoint.gateClosed := backend.gateClosed; endpoint.gateOpen := backend.gateOpen
                endpoint.locked := backend.locked; endpoint.resumed := backend.resumed
                backend.clockEnable := endpoint.clockEnable
                backend.quiesce := endpoint.quiesce; backend.isolate := endpoint.isolate
                backend.program <> endpoint.program; endpoint.result <> backend.result
                endpoint.drainAcks := Mux(sameOwner && selected === i.U && endpoint.quiesce &&
                    armed && !disarmSent && !unsafe, r.io.closeProof.get, 0.U)
            }
        }
    }
    peripherals.cmuRegisters <> fabric.io.clockManagementRegisters.get
    peripherals.uartRegisters <> fabric.io.externalUartRegisters.get
    peripherals.gmacRegisters <> fabric.io.ethernetRegisters.get
    peripherals.streams <> fabric.io.ethernetStreams.get
    fabric.io.externalUartIrq.get := peripherals.uartIrq
    fabric.io.sources := io.sources | (peripherals.gmacIrq.asUInt << CommonPlatformAbi.interruptBit(5)) |
        (peripherals.cmuIrq.asUInt << CommonPlatformAbi.interruptBit(7))
    peripherals.uartRx := io.uartRx; io.uartTx := peripherals.uartTx
    peripherals.gmiiRxData := io.gmiiRxData; peripherals.gmiiRxValid := io.gmiiRxValid
    peripherals.gmiiRxError := io.gmiiRxError; peripherals.linkUp := io.linkUp
    peripherals.triSpeedRgmii.get <> io.triSpeedRgmii
    io.gmiiTxData := peripherals.gmiiTxData; io.gmiiTxEnable := peripherals.gmiiTxEnable
    io.gmiiTxError := peripherals.gmiiTxError; io.mdc := peripherals.mdc
    peripherals.mdioIn := io.mdioIn; io.mdioOut := peripherals.mdioOut; io.mdioOe := peripherals.mdioOe

    io.retire := 0.U.asTypeOf(io.retire)
    io.trap := 0.U.asTypeOf(io.trap)
    if (profile.kind == "i1") {
        val cpu = withClockAndReset(cpuClock, cpuFunctionalReset) {
            Module(new CommonI1CpuTile(profile.i1, boundary))
        }
        crossing.cpu <> cpu.io.bus
        runtime.foreach(_.io.cpuHeld := cpu.io.runtimeHeld.get)
        io.retire(0).valid := cpu.io.retire.valid && !cpu.io.retire.bits.trap
        io.retire(0).bits.pc := cpu.io.retire.bits.pc
        io.retire(0).bits.instruction := cpu.io.retire.bits.instruction
        io.retire(0).bits.nextPc := cpu.io.retire.bits.nextPc
        io.retire(0).bits.rd := cpu.io.retire.bits.rd
        io.retire(0).bits.writesRd := cpu.io.retire.bits.writesRd
        io.retire(0).bits.data := cpu.io.retire.bits.data
        io.trap.valid := cpu.io.trapTaken; io.trap.bits.pc := cpu.io.trapPc
        io.trap.bits.cause := cpu.io.trapCause
        io.cpuCycles := cpu.io.cycles; io.instructions := cpu.io.instructions
    } else {
        val cpu = withClockAndReset(cpuClock, cpuRelease.resetOut) {
            Module(new CommonA1CpuTile(a1CpuConfig, boundary, a1MemoryProfile,
                sideEffectFreeFetchRanges = Seq(soc.core.ooo.SideEffectFreeFetchRange(
                    CommonPlatformAbi.ramBase, fabric.ramBytes))))
        }
        crossing.cpu <> cpu.io.bus
        runtime.foreach(_.io.cpuHeld := cpu.io.runtimeHeld.get)
        cpu.io.hold := false.B; cpu.io.inspectRegister := 0.U
        for (i <- 0 until 2) {
            io.retire(i).valid := cpu.io.commit(i).valid
            io.retire(i).bits.pc := cpu.io.commit(i).bits.pc
            io.retire(i).bits.instruction := cpu.io.commit(i).bits.instruction
            io.retire(i).bits.nextPc := cpu.io.commit(i).bits.nextPc
            io.retire(i).bits.rd := cpu.io.commit(i).bits.rd
            io.retire(i).bits.writesRd := cpu.io.commit(i).bits.writesRd
            io.retire(i).bits.data := cpu.io.commit(i).bits.data
        }
        io.trap.valid := cpu.io.trap.valid; io.trap.bits.pc := cpu.io.trap.bits.pc
        io.trap.bits.cause := cpu.io.trap.bits.cause
        val counters = withClockAndReset(cpuClock, cpuRelease.resetOut) {
            val cycles = RegInit(0.U(64.W)); val retired = RegInit(0.U(64.W))
            cycles := cycles + 1.U; retired := retired + PopCount(cpu.io.commit.map(_.valid))
            (cycles, retired)
        }
        io.cpuCycles := counters._1; io.instructions := counters._2
    }
    io.fabricCycles := withClockAndReset(fabricClock, fabricRelease.resetOut) {
        val cycles = RegInit(0.U(64.W)); cycles := cycles + 1.U; cycles
    }
    if (performanceTelemetry) {
        val monitor = Module(new ClockPerformanceTelemetry(windowCycles = telemetryWindowCycles,
            retirementLanes = if (profile.kind == "a1") 2 else 1))
        monitor.secondRetire.foreach(_ := io.retire(1).valid)
        monitor.sourceClock := fabricClock; monitor.alwaysOnClock := alwaysOnClock
        monitor.managedClocks(0) := cpuClock; monitor.managedClocks(1) := fabricClock
        monitor.commonReset := commonColdReset
        monitor.registers <> peripherals.telemetryRegisters.get
        peripherals.telemetrySourceIdle.get := monitor.sourceIdle
        peripherals.telemetryAonIdle.get := monitor.aonIdle
        for (n <- 0 until 2) {
            // A busy transition invalidates its complete measurement window.
            // Status ownership is AON; no asynchronous control enters the meter.
            monitor.invalidate(n) := peripherals.rateStatus.get(n).busy || rateFatal.get
        }
        val data = crossing.cpu.coherent(1)
        // ABI2 follows A1's actual uncached/MMIO adapter (lane0); ABI1
        // retains I1 lane1. Do not label A1 PTW/cache fallback as MMIO traffic.
        val scalar = crossing.cpu.scalar(if (profile.kind == "a1") 0 else 1)
        val refill = crossing.cpu.lineGrant(1)
        // I1 and A1 receive cache-line data here, not on D (which carries ReleaseAck).
        // Count one actual 64-byte refill per edge; never OR/sum concurrent D acknowledgements.
        monitor.events(0) := VecInit(Seq(io.retire(0).valid, scalar.request.fire,
            data.a.fire, data.a.valid && !data.a.ready, refill.fire,
            refill.valid && !refill.ready, !io.retire.map(_.valid).reduce(_ || _))).asUInt
        val memory = fabric.io.ddrAxi.get
        monitor.events(1) := VecInit(Seq(memory.ar.fire, memory.ar.valid && !memory.ar.ready,
            memory.aw.fire, memory.aw.valid && !memory.aw.ready, memory.r.fire,
            memory.w.fire, memory.r.valid && !memory.r.ready)).asUInt
    }
    io.timeSnapshot := crossing.cpu.timeSnapshot
    io.cpuLinkReady := crossing.cpuLinkReady; io.fabricLinkReady := crossing.fabricLinkReady
    io.cpuTransportEmpty := crossing.cpuTransportEmpty; io.fabricTransportEmpty := crossing.fabricTransportEmpty
    io.maintenancePending := fabric.io.maintenancePending; io.homeDrained := fabric.io.homeDrained
}

/** Firmware owns profiles; hardware validates each submitted integer tuple.
  * This policy never asserts physical or SoC timing qualification.
  */
object CommonDiagnosticRateProfile {
    val option = "software-parameters"
    val domains: Seq[ClockRateParams] = Seq(300000000L, 250000000L).map(max =>
        ClockRateParams(minimumHz = 10000000L, maximumHz = max, stepHz = 1L,
            admission = ClockRateAdmission.Diagnostic, softwareParameters = true))
}
