package soc.platform

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLBurst, TLOpcode, TLParams}
import soc.core.ooo._
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.RegisterPort
import soc.ip.dma.{EthernetAxisWord, EthernetPacketDma, MemoryCopyDma}
import soc.ip.tilelink.{TwoMasterTileLinkArbiter, TwoMasterTwoBankTileLinkCrossbar}
import soc.ip.timer.MachineTimer
import soc.ip.uart.UartConsole

/** Passive accepted-obligation accounting. These counters never manufacture a
  * response or alter throughput. In particular A-channel acceptance is not a
  * completed write, and coherent A ownership survives through the E handshake.
  */
private[platform] object CommonFabricObligations {
    def count(enter: Bool, leave: Bool, name: String, maximum: Int = 64): UInt = {
        val value = RegInit(0.U(log2Ceil(maximum + 1).W)).suggestName(name)
        when(enter =/= leave) { value := Mux(enter, value + 1.U, value - 1.U) }
        when(leave) { assert(value =/= 0.U || enter, s"$name response without accepted owner") }
        when(enter && !leave) { assert(value < maximum.U, s"$name owner capacity exceeded") }
        value
    }

    def ulIdle(port: TLBundle, params: TLParams, name: String): Bool = {
        val aLeft = RegInit(0.U(TLBurst.beats(port.a.bits.size, params).getWidth.W))
            .suggestName(name + "ABeats")
        val dLeft = RegInit(0.U(TLBurst.beats(port.d.bits.size, params).getWidth.W))
            .suggestName(name + "DBeats")
        val aBeats = TLBurst.beats(port.a.bits.size, params)
        val dBeats = TLBurst.beats(port.d.bits.size, params)
        val aFirst = aLeft === 0.U
        val dLast = Mux(dLeft === 0.U,
            !TLBurst.hasDataOnD(port.d.bits.opcode) || dBeats === 1.U, dLeft === 1.U)
        when(port.a.fire) {
            aLeft := Mux(aFirst,
                Mux(TLBurst.hasDataOnA(port.a.bits.opcode), aBeats - 1.U, 0.U), aLeft - 1.U)
        }
        when(port.d.fire) {
            dLeft := Mux(dLeft === 0.U,
                Mux(TLBurst.hasDataOnD(port.d.bits.opcode), dBeats - 1.U, 0.U), dLeft - 1.U)
        }
        val owners = count(port.a.fire && aFirst, port.d.fire && dLast, name)
        owners === 0.U && aLeft === 0.U && dLeft === 0.U && !port.a.valid && !port.d.valid
    }

    def coherentIdle(port: TLBundle, lineGrantValid: Bool, params: TLParams, name: String): Bool = {
        val cLeft = RegInit(0.U(TLBurst.beats(port.c.bits.size, params).getWidth.W))
        val cBeats = TLBurst.beats(port.c.bits.size, params)
        val cData = port.c.bits.opcode === TLOpcode.ReleaseData || port.c.bits.opcode === TLOpcode.ProbeAckData
        val cFirst = cLeft === 0.U
        val cLast = Mux(cFirst, !cData || cBeats === 1.U, cLeft === 1.U)
        when(port.c.fire) { cLeft := Mux(cFirst, Mux(cData, cBeats - 1.U, 0.U), cLeft - 1.U) }
        val acquires = count(port.a.fire, port.e.fire, name + "Acquires")
        val releases = count(port.c.fire && cFirst && TLOpcode.isRelease(port.c.bits.opcode),
            port.d.fire && port.d.bits.opcode === TLOpcode.ReleaseAck, name + "Releases")
        val probes = count(port.b.fire,
            port.c.fire && cLast && !TLOpcode.isRelease(port.c.bits.opcode), name + "Probes")
        acquires === 0.U && releases === 0.U && probes === 0.U && cLeft === 0.U &&
            !port.a.valid && !port.b.valid && !port.c.valid && !port.d.valid && !port.e.valid && !lineGrantValid
    }
}

/** The single fabric-side platform shared by either CPU profile.
  *
  * This module runs only on the fabric clock. CPU clock crossing is an explicit
  * external transport; only synchronized aggregate idle observations enter here.
  * Cold reset is the only reset contract: DDR readiness never cancels an owner.
  * The two-client Home is always 1024 lines / four ways / M2W2 with full line
  * grants, independent of the selected CPU. RAM defaults to the current 2 GiB
  * external DDR, with the selected four-slot/two-write production manager.
  */
class CommonMachineFabric(
    val boundary: CommonCpuTilePortParams = CommonCpuTilePortParams(),
    val fpga: FpgaNextConfig = FpgaNextConfig.Selected,
    val features: CommonPlatformFeatures = CommonPlatformFeatures(
        ethernetControl = true, networkDma = true, jtagDownload = false, clockManagement = true),
    val ramBytes: BigInt = BigInt(2) * 1024 * 1024 * 1024,
    val externalDdr: Boolean = true,
    val romWords: Int = CommonPlatformAbi.romWords,
    romFiles: Seq[String] = Seq.empty,
    programmable: Boolean = false,
    vivadoMemories: Boolean = false,
    ramInitFile: String = "",
    ramResponseDelay: Int = 0,
    ramReadLatency: Int = 1,
    val externalUart: Boolean = true,
    peripheralClockHz: Int = 0,
    uartClockHz: Int = 50000000,
    uartReferenceClockHz: Int = 0,
    uartFastDivisorOne: Boolean = false,
    val externalTimer: Boolean = false
) extends Module {
    import CommonFabricObligations._
    private val ramBase = CommonPlatformAbi.ramBase
    private val romBase = CommonPlatformAbi.romBase
    private val romWindowBytes = (ramBase - romBase).toInt
    private val ddr = fpga.ddr
    private val physical = fpga.coreParams
    require(boundary.coherent.sourceBits == 3 && boundary.coherent.sinkBits == 1)
    require(boundary.homeAcquireEntries == 2 && boundary.homeWritebackEntries == 2)
    require(romWords >= 4 && romWords <= CommonPlatformAbi.romWords && isPow2(romWords))
    require(ramBytes >= 65536 && isPow2(ramBytes) && ramBytes <= (BigInt(1) << 31))
    require(externalDdr || ramBytes <= (BigInt(1) << 26))
    require(!vivadoMemories || (!programmable && romWords == CommonPlatformAbi.romWords))
    require(!features.jtagDownload || ramBytes >= 1024 * 1024)
    require(peripheralClockHz == 0 || peripheralClockHz >= 6000000)
    if (externalDdr) ddr.validateSoc()

    val io = IO(new Bundle {
        val tile = Flipped(new CommonCpuTilePort(boundary))
        // Provided by the explicit CDC boundary, already synchronized to this clock.
        val transportCpuEmptySynchronized = Input(Bool())
        val fabricTransportEmpty = Input(Bool())
        val externalMaintenance = Flipped(Decoupled(new CommonTileMaintenanceCommand(boundary)))
        val externalMaintenanceStatus = Output(Valid(new CommonTileMaintenanceStatus(boundary)))
        val runtimeResume = if (boundary.runtimeMaintenance)
            Some(Flipped(Decoupled(UInt(boundary.maintenanceEpochBits.W)))) else None
        val runtimeCancel = if (boundary.runtimeCancellation)
            Some(Flipped(Decoupled(UInt(boundary.maintenanceEpochBits.W)))) else None
        val runtimeComplete = if (boundary.runtimeCancellation)
            Some(Decoupled(new CommonRuntimeCompletion(boundary))) else None
        // Fabric completion was enqueued; this is not a CPU clock-gate acknowledgement.
        val runtimeHeld = if (boundary.runtimeMaintenance)
            Some(Output(Valid(UInt(boundary.maintenanceEpochBits.W)))) else None
        val peripheralClock = if (peripheralClockHz > 0 && !externalUart) Some(Input(Clock())) else None
        val ethernetRegisters = if (features.ethernetControl) Some(new RegisterPort) else None
        val clockManagementRegisters = if (features.clockManagement) Some(new RegisterPort) else None
        val externalUartRegisters = if (externalUart) Some(new RegisterPort) else None
        val externalUartIrq = if (externalUart) Some(Input(Bool())) else None
        val jtagDmi = if (features.jtagDownload) Some(Flipped(new soc.ip.debug.DebugDmiPort(7))) else None
        val jtagLinkUp = if (features.jtagDownload) Some(Input(Bool())) else None
        val ethernetStreams = if (features.networkDma) Some(new Bundle {
            val txData = Decoupled(new EthernetAxisWord)
            val txControl = Decoupled(new EthernetAxisWord)
            val rxData = Flipped(Decoupled(new EthernetAxisWord))
            val rxStatus = Flipped(Decoupled(new EthernetAxisWord))
        }) else None
        val ddrAxi = if (externalDdr) Some(new Axi4MemoryPort(32, ddr.axiIdWidth)) else None
        val ddrReady = if (externalDdr) Some(Input(Bool())) else None
        val ready = Output(Bool())
        val timerTick = Input(Bool())
        val externalTimerRegisters = if (externalTimer) Some(new RegisterPort) else None
        val externalTimerIrq = if (externalTimer) Some(Input(Bool())) else None
        val externalTimeSnapshot = if (externalTimer) Some(Input(UInt(64.W))) else None
        val sources = Input(UInt(CommonPlatformAbi.interruptSources.W))
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val msiError = Output(Bool())
        val maintenancePending = Output(Bool())
        val homeDrained = Output(Bool())
        val allObligationsIdle = Output(Bool())
        val scalarOutstanding = Output(UInt(5.W))
        val program = if (programmable) Some(Input(Valid(new Bundle {
            val index = UInt(log2Ceil(romWords).W)
            val data = UInt(32.W)
        }))) else None
        val ramProgram = if (programmable && !externalDdr) Some(Input(Valid(new Bundle {
            val index = UInt(log2Ceil(ramBytes / 8).W)
            val data = UInt(64.W)
        }))) else None
    })
    io.ready := io.ddrReady.getOrElse(true.B)

    val pending = RegInit(false.B)
    val epoch = Reg(UInt(boundary.maintenanceEpochBits.W))
    val completionHeld = RegInit(false.B)
    val drainStarted = RegInit(false.B)
    val externalOwned = if (boundary.runtimeMaintenance) Some(RegInit(false.B)) else None
    val externalEpoch = if (boundary.runtimeMaintenance) Some(Reg(UInt(boundary.maintenanceEpochBits.W))) else None
    val holdUntilResume = if (boundary.runtimeMaintenance) Some(RegInit(false.B)) else None
    val completionConsumed = if (boundary.runtimeMaintenance) Some(RegInit(false.B)) else None
    val resumeQueued = if (boundary.runtimeMaintenance) Some(RegInit(false.B)) else None
    val cancelRequested = if (boundary.runtimeCancellation) Some(RegInit(false.B)) else None
    val releaseStarted = if (boundary.runtimeCancellation) Some(RegInit(false.B)) else None
    val terminalHeld = if (boundary.runtimeCancellation) Some(RegInit(false.B)) else None
    val externalOpen = if (boundary.runtimeMaintenance)
        !pending && !externalOwned.get && !resumeQueued.get && !io.tile.maintenanceStatus.valid
    else true.B
    io.tile.maintenance.valid := io.externalMaintenance.valid && externalOpen
    io.tile.maintenance.bits := io.externalMaintenance.bits
    io.externalMaintenance.ready := io.tile.maintenance.ready && externalOpen
    if (boundary.runtimeMaintenance) {
        when(io.externalMaintenance.fire) {
            externalOwned.get := true.B
            externalEpoch.get := io.externalMaintenance.bits.epoch
        }
    }
    io.tile.maintenanceStatus.ready := !pending && !resumeQueued.getOrElse(false.B)
    io.externalMaintenanceStatus.valid := io.tile.maintenanceStatus.fire
    io.externalMaintenanceStatus.bits := io.tile.maintenanceStatus.bits
    when(io.tile.maintenanceStatus.fire) {
        val status = io.tile.maintenanceStatus.bits
        assert(status.privateOwnersDrained && status.dirtyWritebackCompleted && status.fetchQuiescent,
            "fabric drain began before matching tile-private flush and fetch quiescence")
        pending := true.B
        epoch := status.epoch
        if (boundary.runtimeMaintenance) {
            holdUntilResume.get := status.holdUntilResume.get
            when(status.holdUntilResume.get) {
                assert(externalOwned.get && status.epoch === externalEpoch.get,
                    "runtime hold has no matching external maintenance owner")
            }
            // An older architectural FENCE.I may finish after an external
            // prepare was accepted. Its ordinary epoch drains independently;
            // external ownership survives until the later held epoch resumes.
        }
    }
    io.maintenancePending := pending
    val scalar = Module(new CommonFabricScalarArbiter(boundary))
    for (lane <- 0 until boundary.scalarPorts) scalar.io.lanes(lane) <> io.tile.scalar(lane)
    // The tile stops new architectural work before its ready epoch. Already
    // accepted CDC requests and probe-generated reservation clears must still
    // drain here, including clears generated after tile-ready by older DMA.
    scalar.io.stop := false.B
    io.scalarOutstanding := scalar.io.outstanding

    val timer = if (externalTimer) None else Some(Module(new MachineTimer()))
    timer.foreach(_.io.tick := io.timerTick)
    io.tile.timerInterrupt := io.externalTimerIrq.getOrElse(timer.get.io.irq)
    io.tile.softwareInterrupt := false.B // Existing MachineTimer has no software-interrupt register.
    io.tile.timeSnapshot := io.externalTimeSnapshot.getOrElse(timer.get.io.timeValue)
    val interrupts = Module(new CommonInterruptFabric())
    io.tile.msi <> interrupts.io.msi
    io.msiError := interrupts.io.msiError

    val uartCdc = if (peripheralClockHz > 0 && !externalUart) {
        val bridge = Module(new soc.ip.bus.RegisterClockDomainBridge)
        bridge.sourceClock := clock
        bridge.destinationClock := io.peripheralClock.get
        bridge.commonReset := reset.asAsyncReset
        Some(bridge)
    } else None
    val uart = if (externalUart) None else if (peripheralClockHz > 0) {
        Some(withClockAndReset(io.peripheralClock.get, uartCdc.get.destinationReset) {
            Module(new UartConsole(clockHz = peripheralClockHz, referenceClockHz = uartReferenceClockHz,
                fastDivisorOne = uartFastDivisorOne))
        })
    } else Some(Module(new UartConsole(clockHz = uartClockHz, referenceClockHz = uartReferenceClockHz,
        fastDivisorOne = uartFastDivisorOne)))
    uartCdc.foreach(_.destination <> uart.get.io.mmio)
    uart.foreach(_.io.rx := io.uartRx)
    io.uartTx := uart.map(_.io.tx).getOrElse(true.B)
    val uartRegisters = io.externalUartRegisters.getOrElse(uartCdc.map(_.source).getOrElse(uart.get.io.mmio))
    val uartIrq = uartCdc.map { bridge =>
        val synchronizer = Module(new soc.ip.bus.CdcLevel)
        synchronizer.clockIn := clock
        synchronizer.resetIn := bridge.sourceReset
        synchronizer.levelIn := withClockAndReset(io.peripheralClock.get, bridge.destinationReset) {
            RegNext(uart.get.io.irq, false.B)
        }
        synchronizer.levelOut
    }.getOrElse(io.externalUartIrq.getOrElse(uart.get.io.irq))

    val dma = Module(new MemoryCopyDma(ramBase = ramBase, ramBytes = ramBytes,
        lineTransfers = fpga.dmaLineTransfers, lineYieldCycles = fpga.dmaLineYieldCycles,
        lineEntries = fpga.dmaLineEntries))
    val packetDma = if (features.networkDma) Some(Module(new EthernetPacketDma(
        ramBase = ramBase, ramBytes = ramBytes, maxFrameBytes = fpga.network.maxFrameBytes,
        postedRxSlots = fpga.network.postedRxSlots, memoryCredits = fpga.network.memoryCredits,
        postedTxSlots = fpga.network.postedTxSlots))) else None
    packetDma.foreach { network =>
        io.ethernetStreams.get.txData <> network.io.txData
        io.ethernetStreams.get.txControl <> network.io.txControl
        network.io.rxData <> io.ethernetStreams.get.rxData
        network.io.rxStatus <> io.ethernetStreams.get.rxStatus
    }
    val jtagLoader = if (features.jtagDownload) Some(Module(new soc.ip.debug.JtagRamLoader(
        ramBase, (ramBase + ramBytes - 0x4000).min(BigInt("ffff8000", 16)) - 0x80000))) else None
    jtagLoader.foreach { loader => loader.io.dmi <> io.jtagDmi.get; loader.io.linkUp := io.jtagLinkUp.get }
    interrupts.io.sources := io.sources | (uartIrq.asUInt << CommonPlatformAbi.interruptBit(3)) |
        (dma.io.irq.asUInt << CommonPlatformAbi.interruptBit(4)) |
        (packetDma.map(_.io.irq).getOrElse(false.B).asUInt << CommonPlatformAbi.interruptBit(6))

    // Every enabled production window is retained, including the full 256 KiB
    // Ethernet control aperture (the endpoint may implement a smaller native port).
    val regions = CommonPlatformAbi.cpuMmioRegions(features)
    val router = Module(new ParallelRegisterRouter(regions.map(r => (r.base, r.bytes)),
        capacity = 8, bypassMemoryShift = physical.directMemoryResponse))
    router.io.upstream <> scalar.io.memory
    def registers(name: String): RegisterPort = router.io.registers(regions.indexWhere(_.name == name))
    registers("timer") <> io.externalTimerRegisters.getOrElse(timer.get.io.mmio)
    registers("m-aplic") <> interrupts.io.machineRegisters
    registers("s-aplic") <> interrupts.io.supervisorRegisters
    registers("uart") <> uartRegisters
    registers("dma") <> dma.io.control
    packetDma.foreach(_.io.control <> registers("network-dma"))
    jtagLoader.foreach(_.io.control <> registers("jtag"))
    io.ethernetRegisters.foreach(_ <> registers("ethernet"))
    io.clockManagementRegisters.foreach(_ <> registers("cmu"))

    val atomic = Module(new AtomicDataMemory(base = ramBase, bytes = ramBytes,
        registerResponseOwners = true, dmaLineTransfers = fpga.dmaLineTransfers,
        dmaLineEntries = fpga.dmaLineEntries))
    atomic.io.cpu <> router.io.memory
    atomic.io.clearReservation := scalar.io.clearReservation
    if (fpga.dmaLineTransfers) atomic.io.dmaLine.get <> dma.io.line.get
    val networkArbiter = packetDma.map { network =>
        val arbiter = Module(new soc.ip.bus.RegisterArbiter)
        arbiter.io.clients(0) <> dma.io.memory
        arbiter.io.clients(1) <> network.io.memory
        arbiter
    }
    val ordinaryDma = networkArbiter.map(_.io.memory).getOrElse(dma.io.memory)
    val debugArbiter = jtagLoader.map { loader =>
        val arbiter = Module(new soc.ip.bus.RegisterArbiter)
        arbiter.io.clients(0) <> ordinaryDma
        arbiter.io.clients(1) <> loader.io.memory
        arbiter
    }
    val dmaMemory = debugArbiter.map(_.io.memory).getOrElse(ordinaryDma)
    val dmaAdapter = Module(new DmaRegisterDataAdapter)
    dmaAdapter.io.registers <> dmaMemory
    atomic.io.dma <> dmaAdapter.io.data

    // Ordinary AtomicMemory requests are accepted and forwarded on the same
    // edge. An AMO owns its provenance across both physical read/write phases;
    // selecting a different scalar lane later cannot change its probe policy.
    val atomicActive = RegInit(false.B)
    val atomicNeedsLookup = Reg(Bool())
    when(atomic.io.cpu.request.fire && atomic.io.cpu.request.bits.atomic) {
        atomicActive := true.B
        atomicNeedsLookup := scalar.io.needsCoherenceLookup
    }
    when(atomic.io.cpu.response.fire && atomicActive) { atomicActive := false.B }
    val cpuNeedsLookup = Mux(atomicActive, atomicNeedsLookup, scalar.io.needsCoherenceLookup)

    val home = CoherentLineHomeModule.build(params = boundary.coherent, base = ramBase, bytes = ramBytes,
        nClients = 2, trackedLines = 1024, trackedWays = 4, acquireEntries = 2, writebackEntries = 2,
        mixedReadWrite = true, rawResponseMetadata = physical.rawTileLinkResponseMetadata,
        parallelQualification = physical.parallelHomeQualification, tagConfig = fpga.tags,
        dmaLineTransfers = fpga.dmaLineTransfers, dmaLineEntries = fpga.dmaLineEntries,
        lineTransferDispatchFlow = fpga.lineTransferDispatchFlow, lineReadChannel = ddr.lineReadChannel,
        internalLineGrant = true)
    def finalHome: CoherentLineHomeModule = home
    // Preserve the public platform's two-slot physical request cut. Ready is
    // local occupancy, so scalar/MMIO/Atomic arbitration does not traverse the
    // Home directory and backing-manager ready logic in the same cycle. Store
    // the resolved lookup policy with the payload, never with a later lane.
    val physicalRequests = Module(new DataRequestBuffer(registerHead = true))
    // The barrier starts only with this input and queue empty. Later DMA
    // offers must park before allocation, not acquire a queue owner behind a
    // closed Home and thereby prevent the older epoch from completing.
    physicalRequests.io.upstream.request.valid := atomic.io.memory.request.valid && !drainStarted
    physicalRequests.io.upstream.request.bits := atomic.io.memory.request.bits
    atomic.io.memory.request.ready := physicalRequests.io.upstream.request.ready && !drainStarted
    atomic.io.memory.response <> physicalRequests.io.upstream.response
    physicalRequests.io.requestCpu := atomic.io.memoryRequestCpu && !cpuNeedsLookup
    home.io.upstream <> physicalRequests.io.downstream
    home.io.upstreamRequestCpu := physicalRequests.io.downstreamRequestCpu
    if (fpga.dmaLineTransfers) home.io.dmaLine.get <> atomic.io.memoryLine.get
    for (client <- 0 until boundary.coherentClients) {
        home.io.clients(client) <> io.tile.coherent(client)
        io.tile.lineGrant(client) <> home.io.lineGrants.get(client)
    }
    val bridgeParams = boundary.coherent.copy(sinkBits = 1)
    val upstreamParams = boundary.instruction.copy(sinkBits = 1)
    val managerParams = upstreamParams.copy(sourceBits = upstreamParams.sourceBits + 1)
    val bridge = Module(new OrderedTileLinkBridge(params = bridgeParams, orderedWrites = true,
        orderedMixedAccesses = true, orderedWriteBankBase = ramBase, allowWriteErrors = true,
        flowHeadResponse = physical.flowTileLinkResponse, allowPartialWrites = features.networkDma))
    bridge.io.data <> home.io.downstream
    val arbiter = Module(new TwoMasterTileLinkArbiter(bridgeParams,
        rawResponseMetadata = physical.rawTileLinkResponseMetadata,
        rawRequestMetadata = physical.registeredFabricBoundary))
    arbiter.io.masters(0) <> bridge.io.tl
    CoherentHomeUlBoundary.connect(home.io.line, arbiter.io.masters(1),
        registerRequests = fpga.registeredHomeRequestBoundary)
    val crossbar = Module(new TwoMasterTwoBankTileLinkCrossbar(upstreamParams,
        base = romBase, bankBytes = romWindowBytes, secondBankBytes = ramBytes,
        prefixAddressDecode = physical.prefixTileLinkDecode,
        rawResponseMetadata = physical.rawTileLinkResponseMetadata,
        rawRequestMetadata = physical.registeredFabricBoundary))
    def fabricMaster(master: TLBundle): TLBundle = {
        if (physical.registeredFabricBoundary) {
            val stage = Module(new soc.ip.tilelink.RegisteredTileLinkBoundary(upstreamParams))
            stage.io.upstream <> master
            stage.io.downstream
        } else master
    }
    crossbar.io.masters(0) <> fabricMaster(arbiter.io.manager)
    crossbar.io.masters(1) <> fabricMaster(io.tile.instructionFetch)
    val rom = Module(new InstructionRom(romWords, romBase, romFiles, programmable, vivadoNative = vivadoMemories))
    val romManager = Module(new TileLinkInstructionRomAdapter(romWords, base = romBase, params = managerParams,
        bufferedReplies = physical.bufferedRomReplies, completeReadBeat = true))
    romManager.io.tl <> crossbar.io.banks(0)
    rom.io.fetch <> romManager.io.rom
    rom.io.write.foreach(_ := io.program.get)
    private var ddrManager: Option[TileLinkAxi4Bridge] = None
    def ddrManagerInstance: Option[TileLinkAxi4Bridge] = ddrManager
    val managerExtraIdle = WireDefault(true.B)
    if (externalDdr) {
        ddr.validateTileLink(managerParams)
        val manager = Module(new TileLinkAxi4Bridge(tlParams = managerParams,
            axiAddressWidth = 32, axiIdWidth = ddr.axiIdWidth, maxBurstBeats = ddr.maxBurstBeats,
            maxOutstanding = ddr.maxOutstanding, maxOutstandingWrites = ddr.maxOutstandingWrites,
            unorderedResponses = ddr.unorderedResponses, writeCollectionFlow = ddr.writeCollectionFlow,
            lineReadChannel = ddr.lineReadChannel, localPayloadWriteEnable = ddr.localPayloadWriteEnable,
            localPayloadWriteRow = ddr.localPayloadWriteRow, localAddressRanges = fpga.localAddressRanges,
            axiAddressBase = ramBase, axiWindowBytes = ramBytes))
        ddrManager = Some(manager)
        manager.io.tl <> crossbar.io.banks(1)
        manager.io.lineRead.foreach(_ <> home.io.lineRead.get)
        io.ddrAxi.get <> manager.io.axi
        val axi = manager.io.axi
        val reads = count(axi.ar.fire, axi.r.fire && axi.r.bits.last, "ddrReadOwners")
        val writes = count(axi.aw.fire, axi.b.fire, "ddrWriteOwners")
        val lineIdle = manager.io.lineRead.map { line =>
            count(line.request.fire, line.response.fire, "ddrLineReadOwners") === 0.U &&
                !line.request.valid && !line.response.valid
        }.getOrElse(true.B)
        managerExtraIdle := reads === 0.U && writes === 0.U && !axi.ar.valid && !axi.aw.valid &&
            !axi.w.valid && !axi.r.valid && !axi.b.valid && lineIdle
    } else {
        require(!ddr.lineReadChannel, "independent DDR line reads require an external DDR manager")
        val manager = Module(new TileLinkDataRamAdapter(params = managerParams,
            burstEnabled = true, burstBase = ramBase, burstBytes = ramBytes))
        val ram = Module(new SynchronousDataRam(bytes = ramBytes.toInt, base = ramBase,
            initFile = ramInitFile, responseDelay = ramResponseDelay, programmable = programmable,
            readLatency = ramReadLatency, vivadoUltraRam = vivadoMemories, allowPartialWrites = features.networkDma))
        manager.io.tl <> crossbar.io.banks(1)
        ram.io.port <> manager.io.memory
        ram.io.program.foreach(_ := io.ramProgram.get)
        managerExtraIdle := !ram.io.busy
    }

    val fetchIdle = ulIdle(io.tile.instructionFetch, boundary.instruction, "fetchOwners")
    val coherentIdleAll = (0 until boundary.coherentClients).map { client =>
        coherentIdle(io.tile.coherent(client), io.tile.lineGrant(client).valid, boundary.coherent,
            "coherent" + client)
    }.reduce(_ && _)
    val romIdle = ulIdle(crossbar.io.banks(0), managerParams, "romOwners")
    val ramIdle = ulIdle(crossbar.io.banks(1), managerParams, "ramOwners")
    val sharedOwners = count(atomic.io.memory.request.fire, atomic.io.memory.response.fire, "sharedNativeOwners")
    val bridgeOwners = count(bridge.io.data.request.fire, bridge.io.data.response.fire, "orderedBridgeOwners")
    val dmaOwners = count(dmaMemory.request.fire, dmaMemory.response.fire, "dmaNativeOwners")
    val msiOwners = count(io.tile.msi.request.fire, io.tile.msi.response.fire, "msiOwners")
    val streamIdle = io.ethernetStreams.map(s =>
        !s.txData.valid && !s.txControl.valid && !s.rxData.valid && !s.rxStatus.valid).getOrElse(true.B)
    val dmaIdle = !dma.io.active && !packetDma.map(_.io.active).getOrElse(false.B) &&
        dmaOwners === 0.U && !dmaMemory.request.valid && !dmaMemory.response.valid && streamIdle &&
        !io.jtagDmi.map(_.request.valid).getOrElse(false.B)
    val nativeIdle = scalar.io.idle && physicalRequests.io.idle && !atomicActive &&
        sharedOwners === 0.U && bridgeOwners === 0.U &&
        !atomic.io.memory.request.valid && !atomic.io.memory.response.valid &&
        !bridge.io.data.request.valid && !bridge.io.data.response.valid
    val interruptIdle = msiOwners === 0.U && !io.tile.msi.request.valid && !io.tile.msi.response.valid
    val transportsIdle = io.transportCpuEmptySynchronized && io.fabricTransportEmpty
    val producersDrained = nativeIdle && coherentIdleAll && fetchIdle && dmaIdle && transportsIdle
    // Register the transition: Home request-valid is itself admission-gated,
    // so its combinational emptiness must never feed drainRequest directly.
    // The captured producer-empty observation separates older accepted work
    // from later autonomous DMA offers. Those future offers remain unaccepted
    // behind the Home barrier until this epoch is consumed, or until explicit
    // matching resume for an opt-in externally owned runtime epoch.
    when(pending && producersDrained && !drainStarted) { drainStarted := true.B }
    home.io.drainRequest := pending && drainStarted
    io.homeDrained := home.io.drainDone
    val acceptedOwnersIdle = scalar.io.idle && physicalRequests.io.idle && !atomicActive && sharedOwners === 0.U &&
        bridgeOwners === 0.U && dmaOwners === 0.U && coherentIdleAll && fetchIdle && transportsIdle
    val producerEpochIdle = Mux(pending, drainStarted && acceptedOwnersIdle, producersDrained)
    io.allObligationsIdle := producerEpochIdle && home.io.drainDone && romIdle && ramIdle &&
        managerExtraIdle && interruptIdle
    when(pending && io.allObligationsIdle && !completionHeld && !completionConsumed.getOrElse(false.B)) { completionHeld := true.B }
    io.tile.fabricDrainedEpoch.valid := completionHeld
    io.tile.fabricDrainedEpoch.bits := epoch
    when(io.tile.fabricDrainedEpoch.fire) {
        completionHeld := false.B
        when(holdUntilResume.getOrElse(false.B)) {
            completionConsumed.foreach(_ := true.B)
        }.otherwise {
            pending := false.B; drainStarted := false.B
        }
    }
    if (boundary.runtimeMaintenance) {
        val resume = io.runtimeResume.get
        val held = pending && holdUntilResume.get && completionConsumed.get
        io.runtimeHeld.get.valid := held && !releaseStarted.getOrElse(false.B)
        io.runtimeHeld.get.bits := epoch
        if (boundary.runtimeCancellation) {
            val cancel = io.runtimeCancel.get
            val complete = io.runtimeComplete.get
            val resumed = io.tile.maintenanceResumed.get
            // Cancellation never revokes an accepted traffic owner. It can be
            // remembered before tile status, even while an older ordinary
            // FENCE drains, but release still waits for this runtime epoch's
            // actual fabric completion to be consumed.
            cancel.ready := externalOwned.get && cancel.bits === externalEpoch.get &&
                !cancelRequested.get && !releaseStarted.get
            when(cancel.fire) { cancelRequested.get := true.B }
            val releasable = held && externalOwned.get && epoch === externalEpoch.get && !releaseStarted.get
            // Only a matching accepted cancel arbitrates against resume. A
            // stale cancel offer must not backpressure a valid normal resume.
            resume.ready := releasable && resume.bits === externalEpoch.get &&
                !cancelRequested.get && !cancel.fire
            when(resume.valid) {
                assert(releasable && resume.bits === externalEpoch.get,
                    "runtime resume is early, duplicate, or has a stale epoch")
            }
            when(releasable && (cancelRequested.get || cancel.fire || resume.fire)) {
                releaseStarted.get := true.B
                resumeQueued.get := true.B
            }
            io.tile.maintenanceResume.get.valid := resumeQueued.get
            io.tile.maintenanceResume.get.bits := externalEpoch.get
            when(io.tile.maintenanceResume.get.fire) { resumeQueued.get := false.B }
            // Home stays closed until the tile has consumed resume and sent
            // its held acknowledgement after real CPU edges with quiesce low.
            resumed.ready := releaseStarted.get && !resumeQueued.get && !terminalHeld.get &&
                resumed.bits === externalEpoch.get
            when(resumed.fire) {
                pending := false.B; drainStarted := false.B
                completionConsumed.get := false.B; holdUntilResume.get := false.B
                terminalHeld.get := true.B
            }
            complete.valid := terminalHeld.get
            complete.bits.epoch := externalEpoch.get
            complete.bits.canceled := cancelRequested.get
            when(complete.fire) {
                terminalHeld.get := false.B
                externalOwned.get := false.B
                cancelRequested.get := false.B
                releaseStarted.get := false.B
            }
        } else {
            resume.ready := held && resume.bits === epoch && !resumeQueued.get
            when(resume.valid) {
                assert(held && resume.bits === epoch && !resumeQueued.get,
                    "runtime resume is early, duplicate, or has a stale epoch")
            }
            when(resume.fire) {
                pending := false.B; drainStarted := false.B
                completionConsumed.get := false.B; holdUntilResume.get := false.B
                resumeQueued.get := true.B
            }
            io.tile.maintenanceResume.get.valid := resumeQueued.get
            io.tile.maintenanceResume.get.bits := epoch
            when(io.tile.maintenanceResume.get.fire) {
                resumeQueued.get := false.B; externalOwned.get := false.B
            }
        }
    }
    when(pending && io.allObligationsIdle && !completionHeld && !completionConsumed.getOrElse(false.B)) {
        assert(home.io.drainRequest && home.io.drainDone,
            "maintenance epoch acknowledged before actual Home completion")
    }
}
