package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.axi.{Axi4ClockDomainBoundary, Axi4MemoryPort}
import soc.ip.bus.{CdcLevel, CdcResetRelease}
import soc.ip.clock.{ClockRateParams, ManagedPeripheralBank}
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
    runtimeControlQualification: Boolean = false
) extends RawModule {
    require(!runtimeDebugAdmission || (profile.kind == "i1" && independentDebugClock),
        "runtime debug isolation requires I1 and an explicit fixed debug clock; A1 is unsupported")
    require(!runtimeNetworkAdmission || runtimeDebugAdmission,
        "network runtime ordering requires the opt-in debug and I1 epoch path")
    require(!runtimeFixedQualification ||
        (runtimeDebugAdmission && independentDdrClock && independentTimebaseClock),
        "fixed-domain runtime proof requires the I1 epoch path and real DDR/timer boundaries")
    require(!runtimeControlQualification || (runtimeFixedQualification && runtimeNetworkAdmission),
        "managed control qualification requires the real network and fixed-domain epoch joins")
    private val boundary = if (runtimeDebugAdmission) profile.boundary.copy(
        runtimeMaintenance = true, runtimeCancellation = true, runtimeInterruptHold = true) else profile.boundary
    require(independentDdrClock || profile.fabricHz == profile.ddrUiHz,
        "a fabric frequency different from fixed DDR UI requires the complete AXI boundary")
    require(independentTimebaseClock || profile.fabricHz == profile.clocks.timebaseHz,
        "a fabric frequency different from fixed timebase requires the timer boundary")
    require(!profile.independentFixedDomains ||
        (independentDdrClock && independentTimebaseClock && independentDebugClock),
        "the independent fixed-domain profile requires DDR, timer and DMI boundaries even at equal rates")
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
        val jtagDmi = Flipped(new DebugDmiPort(7)); val jtagLinkUp = Input(Bool())
        val maintenance = Flipped(Decoupled(new CommonTileMaintenanceCommand(boundary)))
        val runtime = if (runtimeDebugAdmission) Some(new CommonPlatformRuntimePort(boundary)) else None
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
    val crossing = Module(new CommonCpuClockBoundary(boundary, depth = 16))
    crossing.cpuClock := cpuClock; crossing.fabricClock := fabricClock
    crossing.commonColdReset := startupReset

    // Exactly one fabric and one managed peripheral bank, OUTSIDE the CPU choice.
    val fabric = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonMachineFabric(boundary = boundary, fpga = profile.fpga,
            features = profile.features, ramBytes = profile.fpga.ddrBytes, externalDdr = true,
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
        externalRetirementBarrier = true))) else None
    runtime.foreach { r =>
        r.aonClock := alwaysOnClock; r.cpuClock := cpuClock; r.fabricClock := fabricClock
        r.commonColdReset := commonColdReset
        r.io.requests <> io.runtime.get.requests; r.io.resume <> io.runtime.get.resume
        r.io.cancel <> io.runtime.get.cancel; io.runtime.get.held := r.io.held
        io.runtime.get.result <> r.io.result; io.runtime.get.busy := r.io.busy
        io.runtime.get.cleanupFault := r.io.cleanupFault
        io.runtime.get.timeoutSelected := r.io.timeoutSelected
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
    if (!runtimeDebugAdmission) fabric.io.externalMaintenance <> io.maintenance
    io.maintenanceStatus := fabric.io.externalMaintenanceStatus
    if (runtimeDebugAdmission) {
        val debugSequence = Module(new CommonDebugRuntimeSequencer(boundary))
        debugSequence.fabricClock := fabricClock; debugSequence.debugClock := debugClock.get
        debugSequence.commonColdReset := commonColdReset
        debugSequence.source <> io.jtagDmi; fabric.io.jtagDmi.get <> debugSequence.destination
        debugSequence.sourceLinkUp := io.jtagLinkUp
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
        networkSequence.foreach(_.io.fault := debugSequence.fault)
        runtime.get.io.retirementFault.get := debugSequence.fault ||
            (if (runtimeFixedQualification) fixedQualifiers.map(_.fault).reduce(_ || _) else false.B) ||
            controlQualification.map(_.io.fault).getOrElse(false.B)
        val debugFault = Module(new CdcLevel)
        val aonRelease = Module(new CdcResetRelease)
        aonRelease.clockIn := alwaysOnClock; aonRelease.asyncReset := commonColdReset
        debugFault.clockIn := alwaysOnClock; debugFault.resetIn := aonRelease.resetOut
        debugFault.levelIn := debugSequence.fault
        io.runtime.get.debugFault := debugFault.levelOut
    } else if (independentDebugClock) {
        val debugCrossing = Module(new DebugDmiClockBoundary(7))
        debugCrossing.sourceClock := debugClock.get; debugCrossing.destinationClock := fabricClock
        debugCrossing.commonColdReset := commonColdReset
        debugCrossing.source <> io.jtagDmi; fabric.io.jtagDmi.get <> debugCrossing.destination
        debugCrossing.sourceLinkUp := io.jtagLinkUp
        fabric.io.jtagLinkUp.get := debugCrossing.destinationLinkUp
    } else {
        fabric.io.jtagDmi.get <> io.jtagDmi
        fabric.io.jtagLinkUp.get := io.jtagLinkUp
    }
    fabric.io.program.foreach(_ := io.program.get)
    fabric.io.uartRx := true.B // actual UART is the shared managed bank below
    val peripherals = Module(new ManagedPeripheralBank(profile.cmu, profile.cpuHz, profile.uartHz,
        profile.uartBaud, hardwareClocks, networkDmaConfig = profile.fpga.network,
        triSpeedEthernet = true, triSpeedTxFrameSlots = 2, runtimeAdmission = runtimeNetworkAdmission,
        runtimeControlPark = runtimeControlQualification,
        sourceClockHz = profile.fabricHz, rateDomains = Some(Seq(
            ClockRateParams(), ClockRateParams(maximumHz = 150000000L)))))
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
    peripherals.sourceClock := fabricClock; peripherals.alwaysOnClock := alwaysOnClock
    peripherals.rawUartClock := rawUartClock; peripherals.rawTxClock := rawTxClock
    peripherals.rawRxClock := rawRxClock; peripherals.commonReset := commonColdReset
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
        val cpu = withClockAndReset(cpuClock, cpuRelease.resetOut) {
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
            Module(new CommonA1CpuTile(profile.fpga, boundary))
        }
        crossing.cpu <> cpu.io.bus
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
    io.timeSnapshot := crossing.cpu.timeSnapshot
    io.cpuLinkReady := crossing.cpuLinkReady; io.fabricLinkReady := crossing.fabricLinkReady
    io.cpuTransportEmpty := crossing.cpuTransportEmpty; io.fabricTransportEmpty := crossing.fabricTransportEmpty
    io.maintenancePending := fabric.io.maintenancePending; io.homeDrained := fabric.io.homeDrained
}
