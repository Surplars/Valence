package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.uart.UartConsole
import soc.ip.dma.MemoryCopyDma
import soc.ip.timer.MachineTimer
import soc.ip.memory.CacheStallEvents
import soc.ip.tilelink.{TwoBankTileLinkRouter, TwoMasterTileLinkArbiter, TwoMasterTwoBankTileLinkCrossbar}
import soc.bus.tilelink.TLParams
import soc.ip.axi.Axi4MemoryPort

/** Synchronous ROM/RAM machine platform. The optional programming port is only for image loading under reset. */
class MachinePlatform(
    p: OooParams =
        OooParams(speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096, bufferedRamStores = true),
    romWords: Int = 2048,
    romFiles: Seq[String] = Seq.empty,
    programmable: Boolean = false,
    sharedReadCache: Boolean = false,
    sharedReadCacheLines: Int = 16,
    coherentLineCache: Boolean = false,
    coherentLineCacheLines: Int = 0,
    ramResponseDelay: Int = 0,
    tileLinkMemory: Boolean = false,
    splitTileLinkMemory: Boolean = false,
    tileLinkFetch: Boolean = false,
    instructionLineCacheLines: Int = 16,
    ramBytes: BigInt = 4096,
    translationService: Boolean = false,
    translationLevels: Int = 4,
    pteCacheEntries: Int = 8,
    coreDataTranslation: Boolean = false,
    coreInstructionTranslation: Boolean = false,
    ramInitFile: String = "",
    bufferCoherentResponses: Boolean = false,
    vivadoMemories: Boolean = false,
    ramReadLatency: Int = 1,
    uartClockHz: Int = 40000000,
    uartFastDivisorOne: Boolean = false,
    externalDdr: Boolean = false,
    registerCoherentResponses: Boolean = false,
    uartReferenceClockHz: Int = 0,
    coherentLineCacheWays: Int = 1,
    instructionLineCachePrefetch: Boolean = true,
    registerPhysicalResponseOwners: Boolean = false,
    stagedMemoryFabric: Boolean = false,
    bufferTranslatedResponses: Boolean = false,
    peripheralClockHz: Int = 0,
    ethernetControl: Boolean = false,
    ethernetDma: Boolean = false,
    clockManagement: Boolean = false,
    externalUart: Boolean = false
) extends Module {
    private val romBase = BigInt("80000000", 16)
    require(peripheralClockHz == 0 || peripheralClockHz >= 6000000)
    private val ramBase = p.speculativeRamBase
    private val romWindowBytes = ramBase - romBase
    require(Set(2, 4).contains(p.renameWidth) && p.speculativeRamBytes == ramBytes)
    require(ramBase >= romBase + BigInt(romWords) * 4 && ramBase % 64 == 0)
    require(!tileLinkFetch || (romWindowBytes.isValidInt && isPow2(romWindowBytes.toInt) &&
        romBase % romWindowBytes == 0))
    require(!vivadoMemories || !programmable)
    require(ramBytes >= 4096 && ramBytes <= (BigInt(1) << (if (externalDdr) 31 else 26)) && isPow2(ramBytes))
    require(!externalDdr || (tileLinkMemory && tileLinkFetch && !splitTileLinkMemory))
    require(romWords >= 4 && romWords <= 32768 && isPow2(romWords))
    require(!splitTileLinkMemory || tileLinkMemory)
    require(!splitTileLinkMemory || ramBytes == 4096)
    require(!tileLinkFetch || tileLinkMemory)
    require(instructionLineCacheLines == 0 || (instructionLineCacheLines >= 4 &&
        instructionLineCacheLines <= 256 && isPow2(instructionLineCacheLines)))
    require(!translationService || (tileLinkMemory && Set(3, 4, 5).contains(translationLevels)))
    require(!translationService || Set(4, 8, 16).contains(pteCacheEntries))
    require(!coreDataTranslation || translationService)
    require(!coreInstructionTranslation || translationService)
    require(!coherentLineCache || (tileLinkMemory && tileLinkFetch && !sharedReadCache))
    require(!ethernetDma || coherentLineCache,
        "network DMA requires the probed coherent CPU/DMA memory boundary")
    require(!bufferCoherentResponses || coherentLineCache)
    require(!registerCoherentResponses || bufferCoherentResponses)
    require(!p.registeredTranslatedResponses || bufferTranslatedResponses)
    require(!p.parallelFetchAddresses || tileLinkFetch,
        "parallel fetch addresses require the physical TileLink fetch bridge")
    require(!p.prefixTileLinkDecode || (tileLinkMemory && tileLinkFetch),
        "prefix TileLink decode requires the two-master physical memory crossbar")
    require(!(p.rawTileLinkResponseMetadata || p.bufferedRomReplies) || (tileLinkMemory && tileLinkFetch),
        "raw TL replies and ROM credit buffering require the physical memory/fetch fabric")
    require(!p.directMemoryResponse || stagedMemoryFabric)
    require(!p.registeredFabricBoundary || (stagedMemoryFabric && tileLinkFetch),
        "registered fabric boundaries require the physical data/fetch fabric")
    require(!registerPhysicalResponseOwners || (translationService && tileLinkMemory),
        "registered physical response ownership requires the ordered TileLink memory boundary")
    require(!stagedMemoryFabric || (coreDataTranslation && tileLinkMemory && registerPhysicalResponseOwners),
        "staged memory fabric requires translated data and registered physical ownership")
    require(!bufferTranslatedResponses ||
        (stagedMemoryFabric && bufferCoherentResponses && !registerCoherentResponses),
        "relocated CPU response credits require the staged fabric and flow-through response mode")
    require(Set(1, 2).contains(coherentLineCacheWays))
    require(coherentLineCacheLines == 0 || (coherentLineCache && coherentLineCacheLines >= 2 &&
        coherentLineCacheLines <= ramBytes / 64 && isPow2(coherentLineCacheLines)))
    private val fetchWords = if (p.compressedInstructions && p.renameWidth == 4) 4 else 2
    val io = IO(new Bundle {
        val peripheralClock = if (peripheralClockHz > 0) Some(Input(Clock())) else None
        val ethernetRegisters = if (ethernetControl) Some(new soc.ip.bus.RegisterPort) else None
        val clockManagementRegisters = if (clockManagement) Some(new soc.ip.bus.RegisterPort) else None
        val externalUartRegisters = if (externalUart) Some(new soc.ip.bus.RegisterPort) else None
        val externalUartIrq = if (externalUart) Some(Input(Bool())) else None
        val ethernetStreams = if (ethernetDma) Some(new Bundle {
            val txData = Decoupled(new soc.ip.dma.EthernetAxisWord)
            val txControl = Decoupled(new soc.ip.dma.EthernetAxisWord)
            val rxData = Flipped(Decoupled(new soc.ip.dma.EthernetAxisWord))
            val rxStatus = Flipped(Decoupled(new soc.ip.dma.EthernetAxisWord))
        }) else None
        val ddrAxi = if (externalDdr) Some(new Axi4MemoryPort(32, 4)) else None
        val ddrReady = if (externalDdr) Some(Input(Bool())) else None
        val timerTick       = Input(Bool())
        val sources         = Input(UInt(31.W))
        val uartRx          = Input(Bool())
        val uartTx          = Output(Bool())
        val commitEnable    = Input(Bool())
        val commit          = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val trap            = Output(Valid(new HeadException(p)))
        val redirect        = Output(Valid(new FrontendRedirect(p)))
        val recovering      = Output(Bool())
        val fetchPc         = Output(UInt(64.W))
        val fetchWait       = Output(Bool())
        val msiError        = Output(Bool())
        val externalPending = Output(UInt(2.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue  = Output(UInt(64.W))
        val translation = if (translationService) Some(Vec(2 - (if (coreDataTranslation) 1 else 0) -
            (if (coreInstructionTranslation) 1 else 0),
            Flipped(new SvTranslationPort))) else None
        val translationFlush = if (translationService) Some(Input(Bool())) else None
        val translationEvents = if (translationService) Some(Output(new Bundle {
            val hit = Vec(2, Bool())
            val walk = Vec(2, Bool())
            val pteRead = Vec(2, Bool())
            val pteCacheHit = Vec(2, Bool())
            val idle = Vec(2, Bool())
            val flush = Bool()
            val flushPending = Bool()
            val vmState = new VmCsrState
        })) else None
        val activity        = if (programmable) Some(Output(new Bundle {
            val dmaActive        = Bool()
            val cpuMemoryFire    = Bool()
            val dmaMemoryFire    = Bool()
            val cacheStalls      = new CacheStallEvents
            val cacheHit         = Bool()
            val cacheMiss        = Bool()
            val coherentCacheProfile = new CoherentCacheProfile
            val coherentReleaseData = Bool()
            val coherentProbeAckData = Bool()
            val lineFillGetFire  = Bool()
            val lineFillGetAddress = UInt(64.W)
            val ramRequestStall  = Bool()
            val ramResponseStall = Bool()
            val fetchGetFire     = Bool()
            val fetchGetAddress  = UInt(64.W)
            val fetchGetSize     = UInt(3.W)
            val robOccupancy     = UInt(p.countBits.W)
            val headProfile      = new HeadProfile
            val issueCount       = UInt(log2Ceil(p.issueWidth + 1).W)
            val memoryBusy       = Bool()
        }))
        else None
        val program = if (programmable) Some(Input(new Bundle {
            val hold  = Bool()
            val write = Bool()
            val index = UInt(log2Ceil(romWords).W)
            val data  = UInt(32.W)
        }))
        else None
        val ramProgram = if (programmable && translationService && !externalDdr) Some(Input(new Bundle {
            val write = Bool()
            val index = UInt(log2Ceil(ramBytes / 8).W)
            val data = UInt(64.W)
        })) else None
    })
    val hold       = io.program.map(_.hold).getOrElse(false.B) ||
        io.ddrReady.map(ready => !ready).getOrElse(false.B)
    val core       = Module(new MappedMachineCore(p.copy(machineSystem = true, atomicMemory = true,
        pmpEntries = 16, virtualMemoryLevels = if (translationService) translationLevels else 0),
        dataTranslation = coreDataTranslation, stagedMemoryFabric = stagedMemoryFabric,
        bufferTranslatedResponses = bufferTranslatedResponses))
    val frontend   = Module(new SynchronousFetch(16, p.compressedInstructions, p.frontendCacheSets,
        p.renameWidth, stableFaultMetadata = p.stableFetchFaultMetadata, alignedFetchPmp = p.alignedFetchPmp,
        rawFetchPresence = p.rawFetchPresence, parallelFetchTagLookup = p.parallelFetchTagLookup,
        parallelAlignment = p.parallelFetchAlignment, registeredWindow = p.registeredFetchWindow))
    val fetchAdapter = if (coreInstructionTranslation) {
        val adapter = Module(new InstructionTranslationAdapter(p.copy(machineSystem = true,
            virtualMemoryLevels = translationLevels, pmpEntries = 16)))
        adapter.reset := reset.asBool || hold
        adapter.io.virtual <> frontend.io.memory
        adapter.io.vmState := core.io.vmState.get
        adapter.io.privilege := core.io.fetchPrivilege.get
        adapter.io.pmpState := core.io.pmpState.get
        Some(adapter)
    } else None
    val fetchTranslation = fetchAdapter.map(_.io.translation)
    val translatedFetch = fetchAdapter.map(_.io.physical).getOrElse(frontend.io.memory)
    val physicalFetch = if (p.bufferedFetchRequests) {
        val requests = Module(new InstructionRequestBuffer(translatedFetch.packetWords,
            p.flowThroughFetchRequests, p.independentFetchCapture))
        requests.reset := reset.asBool || hold
        requests.io.upstream <> translatedFetch
        requests.io.downstream
    } else translatedFetch
    val lineFetchIdle = WireDefault(true.B)
    val rom = Module(new InstructionRom(romWords, romBase, romFiles, programmable,
        vivadoNative = vivadoMemories))
    val ram = if (externalDdr) None else Some(Module(new SynchronousDataRam(bytes = if (splitTileLinkMemory) 2048 else ramBytes.toInt,
        base = ramBase, initFile = ramInitFile, responseDelay = ramResponseDelay,
        programmable = programmable && translationService, readLatency = ramReadLatency,
        vivadoUltraRam = vivadoMemories, allowPartialWrites = ethernetDma)))
    val secondRam = if (splitTileLinkMemory) {
        Some(Module(new SynchronousDataRam(bytes = 2048, base = ramBase + 2048,
            responseDelay = ramResponseDelay, allowPartialWrites = ethernetDma)))
    } else None
    val uartCdc = if (peripheralClockHz > 0 && !externalUart) {
        val bridge = Module(new soc.ip.bus.RegisterClockDomainBridge)
        bridge.sourceClock := clock
        bridge.destinationClock := io.peripheralClock.get
        bridge.commonReset := (reset.asBool || hold).asAsyncReset
        Some(bridge)
    } else None
    val uart = if (externalUart) None else if (peripheralClockHz > 0) {
        Some(withClockAndReset(io.peripheralClock.get, uartCdc.get.destinationReset) {
            Module(new UartConsole(clockHz = peripheralClockHz,
                fastDivisorOne = uartFastDivisorOne, referenceClockHz = uartReferenceClockHz))
        })
    } else Some(Module(new UartConsole(clockHz = uartClockHz,
        fastDivisorOne = uartFastDivisorOne, referenceClockHz = uartReferenceClockHz)))
    uartCdc.foreach(_.destination <> uart.get.io.mmio)
    val uartRegisters = io.externalUartRegisters.getOrElse(uartCdc.map(_.source).getOrElse(uart.get.io.mmio))
    val uartRouter = if (!stagedMemoryFabric)
        Some(Module(new CoreRegisterRouter(BigInt("10000000", 16), bytes = 8))) else None
    uartRouter.foreach(_.io.registers <> uartRegisters)
    uart.foreach(_.io.rx := io.uartRx)
    io.uartTx := uart.map(_.io.tx).getOrElse(true.B)
    val timer       = Module(new MachineTimer())
    val timerRouter = if (!stagedMemoryFabric)
        Some(Module(new CoreRegisterRouter(BigInt("02000000", 16), bytes = 65536))) else None
    val dma       = Module(new MemoryCopyDma(ramBase = ramBase, ramBytes = ramBytes))
    val packetDma = if (ethernetDma) Some(Module(new soc.ip.dma.EthernetPacketDma(
        ramBase = ramBase, ramBytes = ramBytes))) else None
    packetDma.foreach { network =>
        io.ethernetStreams.get.txData <> network.io.txData
        io.ethernetStreams.get.txControl <> network.io.txControl
        network.io.rxData <> io.ethernetStreams.get.rxData
        network.io.rxStatus <> io.ethernetStreams.get.rxStatus
    }
    val dmaRouter = if (!stagedMemoryFabric)
        Some(Module(new CoreRegisterRouter(BigInt("10001000", 16), bytes = 40))) else None
    val ethernetRouter = if (ethernetControl && !stagedMemoryFabric)
        Some(Module(new CoreRegisterRouter(BigInt("10040000", 16), bytes = 0x40000))) else None
    val packetDmaRouter = if (ethernetDma && !stagedMemoryFabric)
        Some(Module(new CoreRegisterRouter(BigInt("10002000", 16), bytes = 256))) else None
    val cmuRouter = if (clockManagement && !stagedMemoryFabric)
        Some(Module(new CoreRegisterRouter(BigInt("10080000", 16), bytes = 4096))) else None
    val platformRouter = if (stagedMemoryFabric) Some(Module(new ParallelRegisterRouter(Seq(
        (BigInt("02000000", 16), BigInt(65536)),
        (BigInt("10000000", 16), BigInt(8)),
        (BigInt("10001000", 16), BigInt(40))
    ) ++ (if (ethernetControl) Seq((BigInt("10040000", 16), BigInt(0x40000))) else Seq.empty) ++
        (if (ethernetDma) Seq((BigInt("10002000", 16), BigInt(256))) else Seq.empty) ++
        (if (clockManagement) Seq((BigInt("10080000", 16), BigInt(4096))) else Seq.empty),
        bypassMemoryShift = p.directMemoryResponse))) else None
    val platformUpstream = platformRouter.map(_.io.upstream).getOrElse(timerRouter.get.io.upstream)
    val platformMemory = platformRouter.map(_.io.memory)
        .getOrElse(cmuRouter.map(_.io.memory).getOrElse(packetDmaRouter.map(_.io.memory)
            .getOrElse(ethernetRouter.map(_.io.memory).getOrElse(dmaRouter.get.io.memory))))
    platformRouter match {
        case Some(fabric) =>
            fabric.io.registers(0) <> timer.io.mmio
            fabric.io.registers(1) <> uartRegisters
            fabric.io.registers(2) <> dma.io.control
            if (ethernetControl) io.ethernetRegisters.get <> fabric.io.registers(3)
            packetDma.foreach(_.io.control <> fabric.io.registers(if (ethernetControl) 4 else 3))
            if (clockManagement) io.clockManagementRegisters.get <> fabric.io.registers(
                3 + (if (ethernetControl) 1 else 0) + (if (ethernetDma) 1 else 0))
        case None =>
            timerRouter.get.io.registers <> timer.io.mmio
            uartRouter.get.io.upstream <> timerRouter.get.io.memory
            dmaRouter.get.io.upstream <> uartRouter.get.io.memory
            dmaRouter.get.io.registers <> dma.io.control
            ethernetRouter.foreach { router =>
                router.io.upstream <> dmaRouter.get.io.memory
                io.ethernetRegisters.get <> router.io.registers
            }
            packetDmaRouter.foreach { router =>
                router.io.upstream <> ethernetRouter.map(_.io.memory).getOrElse(dmaRouter.get.io.memory)
                router.io.registers <> packetDma.get.io.control
            }
            cmuRouter.foreach { router =>
                router.io.upstream <> packetDmaRouter.map(_.io.memory)
                    .getOrElse(ethernetRouter.map(_.io.memory).getOrElse(dmaRouter.get.io.memory))
                io.clockManagementRegisters.get <> router.io.registers
            }
    }
    if (bufferCoherentResponses && !bufferTranslatedResponses) {
        // Decouple CPU response backpressure before it traverses the MMIO routers,
        // private cache, arbiters, and coherence home. Optional non-flow mode also
        // cuts request->ready->same-cycle-response->CPU timing; it adds one cycle.
        val responses = Module(new Queue(new DataResponse, 2, pipe = false, flow = !registerCoherentResponses))
        responses.reset := reset.asBool || hold
        platformUpstream.request <> core.io.memory.request
        responses.io.enq.valid := platformUpstream.response.valid
        responses.io.enq.bits := platformUpstream.response.bits
        platformUpstream.response.ready := responses.io.enq.ready
        core.io.memory.response.valid := responses.io.deq.valid
        core.io.memory.response.bits := responses.io.deq.bits
        responses.io.deq.ready := core.io.memory.response.ready
    } else platformUpstream <> core.io.memory
    timer.io.tick          := io.timerTick
    core.io.timerInterrupt := timer.io.irq
    core.io.timeValue      := timer.io.timeValue
    val shared    = Module(new AtomicDataMemory(
        base = ramBase, bytes = ramBytes, registerResponseOwners = registerPhysicalResponseOwners
    ))
    val privateCacheLines = if (coherentLineCacheLines == 0) (ramBytes / 64).min(128).toInt
        else coherentLineCacheLines
    val privateCache = if (coherentLineCache) Some(Module(new CoherentLineCache(
        base = ramBase, bytes = ramBytes, lines = privateCacheLines, ways = coherentLineCacheWays))) else None
    shared.io.clearReservation          := core.io.trap.valid
    shared.io.dma.request.bits.atomic   := false.B
    shared.io.dma.request.bits.atomicOp := 0.U
    shared.io.dma.request.bits.virtualized := false.B
    shared.io.dma.request.bits.uncached := false.B
    privateCache match {
        case Some(cache) =>
            cache.reset := reset.asBool || hold
            cache.io.flushRequest := core.io.fenceIFlush
            core.io.fenceIFlushReady := cache.io.flushDone
            cache.io.upstream <> platformMemory
            shared.io.cpu <> cache.io.downstream
        case None =>
            core.io.fenceIFlushReady := true.B
            shared.io.cpu <> platformMemory
    }
    val dmaArbiter = packetDma.map { network =>
        val arbiter = Module(new soc.ip.bus.RegisterArbiter)
        arbiter.reset := reset.asBool || hold
        arbiter.io.clients(0) <> dma.io.memory
        arbiter.io.clients(1) <> network.io.memory
        arbiter
    }
    val dmaMemory = dmaArbiter.map(_.io.memory).getOrElse(dma.io.memory)
    if (ethernetDma) {
        val lanes = Module(new DmaRegisterDataAdapter)
        lanes.reset := reset.asBool || hold
        lanes.io.registers <> dmaMemory
        shared.io.dma <> lanes.io.data
    } else {
        shared.io.dma.request.valid        := dmaMemory.request.valid
        shared.io.dma.request.bits.address := dmaMemory.request.bits.address
        shared.io.dma.request.bits.data    := dmaMemory.request.bits.data
        shared.io.dma.request.bits.write   := dmaMemory.request.bits.write
        shared.io.dma.request.bits.size    := dmaMemory.request.bits.size
        shared.io.dma.request.bits.mask    := dmaMemory.request.bits.byteEnable
        dmaMemory.request.ready           := shared.io.dma.request.ready
        dmaMemory.response.valid          := shared.io.dma.response.valid
        dmaMemory.response.bits.data      := shared.io.dma.response.bits.data
        dmaMemory.response.bits.error     := shared.io.dma.response.bits.error
        shared.io.dma.response.ready      := dmaMemory.response.ready
    }
    io.activity.foreach { activity =>
        activity.dmaActive     := dma.io.active || packetDma.map(_.io.active).getOrElse(false.B)
        activity.cpuMemoryFire := privateCache.map(_.io.upstream.request.fire)
            .getOrElse(shared.io.cpu.request.fire)
        activity.dmaMemoryFire := shared.io.dma.request.fire
        activity.robOccupancy := core.io.robOccupancy
        activity.headProfile := core.io.headProfile
        activity.issueCount := core.io.issueCount
        activity.memoryBusy := core.io.memoryBusy
        activity.coherentReleaseData := privateCache.map(cache =>
            cache.io.tl.c.fire && cache.io.tl.c.bits.opcode === soc.bus.tilelink.TLOpcode.ReleaseData)
            .getOrElse(false.B)
        activity.coherentProbeAckData := privateCache.map(cache =>
            cache.io.tl.c.fire && cache.io.tl.c.bits.opcode === soc.bus.tilelink.TLOpcode.ProbeAckData)
            .getOrElse(false.B)
        activity.fetchGetFire := false.B
        activity.fetchGetAddress := 0.U
        activity.fetchGetSize := 0.U
        activity.lineFillGetFire := false.B
        activity.lineFillGetAddress := 0.U
    }
    // UART's async local reset must not be overwritten by the CPU-domain reset
    // loop. With CDC disabled the old reset/hold behavior remains identical.
    for (module <- Seq(core, frontend, rom, dma, shared, timer) ++
        (if (peripheralClockHz == 0) uart.toSeq else Seq.empty) ++
        uartRouter.toSeq ++ dmaRouter.toSeq ++ timerRouter.toSeq ++ platformRouter.toSeq ++ ethernetRouter.toSeq ++
        packetDma.toSeq ++ packetDmaRouter.toSeq ++ cmuRouter.toSeq ++
        ram.toSeq ++ secondRam.toSeq) {
        module.reset := reset.asBool || hold
    }
    io.program.foreach { program =>
        rom.io.write.get.valid      := program.write && program.hold
        rom.io.write.get.bits.index := program.index
        rom.io.write.get.bits.data  := program.data
        when(program.write) { assert(program.hold, "program ROM only with the platform held in reset") }
    }
    io.ramProgram.foreach { program =>
        ram.get.io.program.get.valid := program.write && hold
        ram.get.io.program.get.bits.index := program.index
        ram.get.io.program.get.bits.data := program.data
        when(program.write) { assert(hold, "program RAM only with the platform held in reset") }
    }
    val downstream = if (sharedReadCache) {
        val cache = Module(new CachedDataMemory(sharedReadCacheLines, p.speculativeRamBytes, base = ramBase))
        cache.reset := reset.asBool || hold
        cache.io.upstream <> shared.io.memory
        io.activity.foreach(_.cacheStalls := cache.io.stalls)
        io.activity.foreach(_.cacheHit := cache.io.hit)
        io.activity.foreach(_.cacheMiss := cache.io.miss)
        io.activity.foreach(_.coherentCacheProfile := 0.U.asTypeOf(new CoherentCacheProfile))
        cache.io.memory
    } else {
        io.activity.foreach(_.cacheStalls := 0.U.asTypeOf(new CacheStallEvents))
        io.activity.foreach(_.cacheHit := privateCache.map(_.io.hit).getOrElse(false.B))
        io.activity.foreach(_.cacheMiss := privateCache.map(_.io.miss).getOrElse(false.B))
        io.activity.foreach(_.coherentCacheProfile := privateCache.map(_.io.profile)
            .getOrElse(0.U.asTypeOf(new CoherentCacheProfile)))
        shared.io.memory
    }
    val physicalDataRequestCpu = WireDefault(shared.io.memoryRequestCpu)
    val physicalData = if (translationService) {
        val walkers = Seq.fill(2)(Module(new SvTranslationService(translationLevels)))
        val adapters = Seq.fill(2)(Module(new SvPteDataBridge(pteCacheEntries)))
        val walkerArbiter = Module(new SharedDataArbiter)
        // OrderedTileLinkBridge cannot return a newly accepted DataPort request
        // in the same cycle (its order queue is non-flow). Register only owner
        // visibility, not response data, so L1 hits and delayed replies keep latency.
        val systemArbiter = Module(new SharedDataArbiter(registerPhysicalResponseOwners))
        val coreFlush = Wire(Bool())
        val flush = io.translationFlush.get || coreFlush
        for (i <- 0 until 2) {
            walkers(i).reset := reset.asBool || hold
            adapters(i).reset := reset.asBool || hold
            adapters(i).io.flush := flush
            if (i == 1 && coreDataTranslation) walkers(i).io.client <> core.io.translation.get
            else if (i == 0 && coreInstructionTranslation) walkers(i).io.client <> fetchTranslation.get
            else walkers(i).io.client <> io.translation.get(if (i == 1 && coreInstructionTranslation) 0 else i)
            walkers(i).io.flush := flush
            walkers(i).io.pmpState := core.io.pmpState.get
            adapters(i).io.walk <> walkers(i).io.memory
            walkerArbiter.io.clients(i) <> adapters(i).io.data
            io.translationEvents.get.hit(i) := walkers(i).io.tlbHit
            io.translationEvents.get.walk(i) := walkers(i).io.walkStart
            io.translationEvents.get.pteRead(i) := adapters(i).io.physicalRead
            io.translationEvents.get.pteCacheHit(i) := adapters(i).io.cacheHit
            io.translationEvents.get.idle(i) := walkers(i).io.idle && adapters(i).io.idle
        }
        val ready = io.translationEvents.get.idle.reduce(_ && _)
        core.io.vmFlushReady.get := ready
        coreFlush := core.io.vmFlush.get && ready
        io.translationEvents.get.flush := coreFlush
        io.translationEvents.get.flushPending := core.io.vmFlush.get
        io.translationEvents.get.vmState := core.io.vmState.get
        when(core.io.vmState.get.satp(63, 60) =/= 0.U) {
            if (!coreInstructionTranslation) {
                assert(core.io.fetchPrivilege.get === 3.U,
                    "S/U virtual CPU fetch path is not connected to translation yet")
            }
            if (!coreDataTranslation) {
                assert(core.io.vmState.get.dataPrivilege === 3.U,
                    "CPU virtual data path is not connected to translation yet")
            }
        }
        walkerArbiter.reset := reset.asBool || hold
        systemArbiter.reset := reset.asBool || hold
        systemArbiter.io.clients(0) <> downstream
        systemArbiter.io.clients(1) <> walkerArbiter.io.memory
        physicalDataRequestCpu := systemArbiter.io.memoryRequestClient0 && shared.io.memoryRequestCpu
        systemArbiter.io.memory
    } else downstream
    val physicalRequests = if (stagedMemoryFabric)
        Some(Module(new DataRequestBuffer(registerHead = p.registeredFabricBoundary))) else None
    physicalRequests.foreach { buffer =>
        buffer.reset := reset.asBool || hold
        buffer.io.upstream <> physicalData
        buffer.io.requestCpu := physicalDataRequestCpu
    }
    val homeUpstream = physicalRequests.map(_.io.downstream).getOrElse(physicalData)
    val homeRequestCpu = physicalRequests.map(_.io.downstreamRequestCpu).getOrElse(physicalDataRequestCpu)
    val (ramUpstream, secondRamUpstream) = if (tileLinkMemory) {
        val bridge = Module(new OrderedTileLinkBridge(
            orderedWrites = !splitTileLinkMemory,
            orderedMixedAccesses = !splitTileLinkMemory,
            orderedWriteBankBase = p.speculativeRamBase,
            orderedWriteBankBytes = if (splitTileLinkMemory) 2048 else 0,
            allowWriteErrors = true,
            flowHeadResponse = p.flowTileLinkResponse, allowPartialWrites = ethernetDma))
        bridge.reset := reset.asBool || hold
        val coherentHome = privateCache.map { cache =>
            val home = Module(new CoherentLineHome(base = ramBase, bytes = ramBytes,
                trackedLines = if (privateCacheLines < ramBytes / 64 || coherentLineCacheWays > 1)
                    privateCacheLines else 0, trackedWays = coherentLineCacheWays,
                rawResponseMetadata = p.rawTileLinkResponseMetadata,
                parallelQualification = p.parallelHomeQualification))
            home.reset := reset.asBool || hold
            home.io.upstream <> homeUpstream
            home.io.upstreamRequestCpu := homeRequestCpu
            bridge.io.data <> home.io.downstream
            home.io.clients(0) <> cache.io.tl
            home
        }
        io.activity.foreach { activity =>
            coherentHome.foreach { home =>
                activity.lineFillGetFire := home.io.line.a.fire &&
                    home.io.line.a.bits.opcode === soc.bus.tilelink.TLOpcode.Get &&
                    home.io.line.a.bits.size === 6.U
                activity.lineFillGetAddress := home.io.line.a.bits.address
            }
        }
        if (coherentHome.isEmpty) { bridge.io.data <> homeUpstream }
        if (tileLinkFetch) {
            val upstreamParams = TLParams(addrWidth = 64, dataWidth = 64,
                sourceBits = if (coherentLineCache) 4 else 3)
            val managerParams = upstreamParams.copy(sourceBits = upstreamParams.sourceBits + 1)
            val crossbar = Module(new TwoMasterTwoBankTileLinkCrossbar(upstreamParams,
                base = romBase, bankBytes = romWindowBytes.toInt, secondBankBytes = ramBytes,
                prefixAddressDecode = p.prefixTileLinkDecode, rawResponseMetadata = p.rawTileLinkResponseMetadata,
                rawRequestMetadata = p.registeredFabricBoundary))
            def fabricMaster(master: soc.bus.tilelink.TLBundle): soc.bus.tilelink.TLBundle = {
                if (p.registeredFabricBoundary) {
                    val boundary = Module(new soc.ip.tilelink.RegisteredTileLinkBoundary(upstreamParams))
                    boundary.reset := reset.asBool || hold
                    boundary.io.upstream <> master
                    boundary.io.downstream
                } else master
            }
            val romManager = Module(new TileLinkInstructionRomAdapter(romWords, params = managerParams,
                bufferedReplies = p.bufferedRomReplies))
            for (module <- Seq(crossbar, romManager)) {
                module.reset := reset.asBool || hold
            }
            if (instructionLineCacheLines > 0) {
                val fetchCache = Module(new InstructionLineCache(upstreamParams,
                    ramBase = p.speculativeRamBase, ramBytes = ramBytes,
                    romBytes = romWords * 4, lines = instructionLineCacheLines,
                    packetWords = fetchWords, prefetchEnabled = fetchWords == 4 && instructionLineCachePrefetch,
                    parallelFallbackAddresses = p.parallelFetchAddresses))
                fetchCache.reset := reset.asBool || hold
                physicalFetch <> fetchCache.io.fetch
                crossbar.io.masters(1) <> fabricMaster(fetchCache.io.tl)
                fetchCache.io.pmpState := core.io.pmpState.get
                fetchCache.io.privilege := core.io.fetchPrivilege.get
                fetchCache.io.invalidate := core.io.invalidateFetch
                lineFetchIdle := fetchCache.io.idle
            } else {
                val fetchBridge = Module(new InstructionTileLinkBridge(upstreamParams,
                    immutableBytes = romWords * 4, parallelAddresses = p.parallelFetchAddresses))
                fetchBridge.reset := reset.asBool || hold
                if (fetchWords == 4) {
                    val adapter = Module(new WideInstructionAdapter)
                    adapter.reset := reset.asBool || hold
                    physicalFetch <> adapter.io.wide
                    adapter.io.narrow <> fetchBridge.io.fetch
                } else physicalFetch <> fetchBridge.io.fetch
                crossbar.io.masters(1) <> fabricMaster(fetchBridge.io.tl)
            }
            io.activity.foreach { activity =>
                activity.fetchGetFire := crossbar.io.masters(1).a.fire
                activity.fetchGetAddress := crossbar.io.masters(1).a.bits.address
                activity.fetchGetSize := crossbar.io.masters(1).a.bits.size
            }
            coherentHome match {
                case Some(home) =>
                    val arbiter = Module(new TwoMasterTileLinkArbiter(
                        TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3), p.rawTileLinkResponseMetadata,
                        rawRequestMetadata = p.registeredFabricBoundary))
                    arbiter.reset := reset.asBool || hold
                    bridge.io.tl <> arbiter.io.masters(0)
                    home.io.line <> arbiter.io.masters(1)
                    crossbar.io.masters(0) <> fabricMaster(arbiter.io.manager)
                case None => crossbar.io.masters(0) <> fabricMaster(bridge.io.tl)
            }
            crossbar.io.banks(0) <> romManager.io.tl
            romManager.io.rom <> rom.io.fetch
            if (splitTileLinkMemory) {
                val router = Module(new TwoBankTileLinkRouter(managerParams, base = ramBase,
                    rawResponseMetadata = p.rawTileLinkResponseMetadata))
                val banks = (0 until 2).map(i => Module(new TileLinkDataRamAdapter(
                    params = managerParams, burstEnabled = true,
                    burstBase = p.speculativeRamBase + i * 2048, burstBytes = 2048)))
                router.reset := reset.asBool || hold
                banks.foreach(_.reset := reset.asBool || hold)
                crossbar.io.banks(1) <> router.io.host
                for (i <- 0 until 2) { router.io.banks(i) <> banks(i).io.tl }
                (Some(banks.head.io.memory), Some(banks(1).io.memory))
            } else if (externalDdr) {
                // Coherence/atomics are resolved above this non-coherent DDR boundary.
                // Capacity: one TL transaction, <=16 AXI beats, arbitrary backpressure.
                val manager = Module(new TileLinkAxi4Bridge(tlParams = managerParams,
                    axiAddressWidth = 32, axiIdWidth = 4, maxBurstBeats = 16,
                    axiAddressBase = ramBase, axiWindowBytes = ramBytes))
                manager.reset := reset.asBool || hold
                crossbar.io.banks(1) <> manager.io.tl
                io.ddrAxi.get <> manager.io.axi
                // The manager translates full physical addresses before narrowing to MIG offsets.
                (None, None)
            } else {
                val manager = Module(new TileLinkDataRamAdapter(params = managerParams,
                    burstEnabled = true, burstBase = p.speculativeRamBase, burstBytes = ramBytes))
                manager.reset := reset.asBool || hold
                crossbar.io.banks(1) <> manager.io.tl
                (Some(manager.io.memory), None)
            }
        } else if (splitTileLinkMemory) {
            val router = Module(new TwoBankTileLinkRouter(base = ramBase))
            val banks = (0 until 2).map(i => Module(new TileLinkDataRamAdapter(
                burstEnabled = true, burstBase = p.speculativeRamBase + i * 2048,
                burstBytes = 2048)))
            router.reset := reset.asBool || hold
            banks.foreach(_.reset := reset.asBool || hold)
            bridge.io.tl <> router.io.host
            for (i <- 0 until 2) { router.io.banks(i) <> banks(i).io.tl }
            (Some(banks.head.io.memory), Some(banks(1).io.memory))
        } else {
            val manager = Module(new TileLinkDataRamAdapter(
                burstEnabled = true, burstBase = p.speculativeRamBase, burstBytes = ramBytes))
            manager.reset := reset.asBool || hold
            bridge.io.tl <> manager.io.tl
            (Some(manager.io.memory), None)
        }
    } else (Some(physicalData), None)
    frontend.io.pc     := core.io.fetchPc
    frontend.io.enable := !hold
    frontend.io.invalidate := core.io.invalidateFetch
    frontend.io.pause := core.io.pauseFetch.get
    frontend.io.pmpState := core.io.pmpState.get
    frontend.io.privilege := core.io.fetchPrivilege.get
    frontend.io.virtualized := (if (coreInstructionTranslation)
        core.io.vmState.get.satp(63, 60) =/= 0.U && core.io.fetchPrivilege.get =/= 3.U else false.B)
    core.io.fetchQuiescent.get := frontend.io.quiescent &&
        fetchAdapter.map(_.io.idle).getOrElse(true.B) && lineFetchIdle
    if (!tileLinkFetch) {
        if (fetchWords == 4) {
            val adapter = Module(new WideInstructionAdapter)
            adapter.reset := reset.asBool || hold
            physicalFetch <> adapter.io.wide
            adapter.io.narrow <> rom.io.fetch
        } else physicalFetch <> rom.io.fetch
    }
    core.io.instructions       := frontend.io.instructions
    core.io.instructionFaults   := frontend.io.instructionFaults
    core.io.instructionPageFaults := frontend.io.instructionPageFaults
    core.io.instructionFaultAddresses.foreach(_ := frontend.io.instructionFaultAddresses)
    core.io.commitEnable       := io.commitEnable && !hold
    val uartIrq = uartCdc.map { bridge =>
        val synchronizer = Module(new soc.ip.bus.CdcLevel)
        synchronizer.clockIn := clock
        synchronizer.resetIn := bridge.sourceReset
        val sourceLevel = withClockAndReset(io.peripheralClock.get, bridge.destinationReset) {
            RegNext(uart.get.io.irq, false.B)
        }
        synchronizer.levelIn := sourceLevel
        synchronizer.levelOut
    }.getOrElse(io.externalUartIrq.getOrElse(uart.get.io.irq))
    core.io.sources            := io.sources | (uartIrq.asUInt << 2) | (dma.io.irq.asUInt << 3) |
        (packetDma.map(_.io.irq).getOrElse(false.B).asUInt << 5) // network DMA: APLIC 6
    core.io.inspectRegister    := io.inspectRegister
    ram.foreach { local =>
        val upstream = ramUpstream.get
        local.io.port.request.valid := upstream.request.valid && !hold
        local.io.port.request.bits := upstream.request.bits
        upstream.request.ready := local.io.port.request.ready && !hold
        upstream.response.valid := local.io.port.response.valid && !hold
        upstream.response.bits := local.io.port.response.bits
        local.io.port.response.ready := upstream.response.ready && !hold
    }
    val extraRequestStall  = WireDefault(false.B)
    val extraResponseStall = WireDefault(false.B)
    secondRam.foreach { bank =>
        val upstream = secondRamUpstream.get
        bank.io.port.request.valid  := upstream.request.valid && !hold
        bank.io.port.request.bits   := upstream.request.bits
        upstream.request.ready      := bank.io.port.request.ready && !hold
        upstream.response.valid     := bank.io.port.response.valid && !hold
        upstream.response.bits      := bank.io.port.response.bits
        bank.io.port.response.ready := upstream.response.ready && !hold
        extraRequestStall  := bank.io.port.request.valid && !bank.io.port.request.ready
        extraResponseStall := bank.io.port.response.valid && !bank.io.port.response.ready
    }
    io.activity.foreach { activity =>
        activity.ramRequestStall  := ram.map(local => local.io.port.request.valid && !local.io.port.request.ready).getOrElse(
            io.ddrAxi.get.aw.valid && !io.ddrAxi.get.aw.ready ||
                io.ddrAxi.get.ar.valid && !io.ddrAxi.get.ar.ready) || extraRequestStall
        activity.ramResponseStall := ram.map(local => local.io.port.response.valid && !local.io.port.response.ready).getOrElse(
            io.ddrAxi.get.r.valid && !io.ddrAxi.get.r.ready ||
                io.ddrAxi.get.b.valid && !io.ddrAxi.get.b.ready) || extraResponseStall
    }
    io.commit          := core.io.commit
    io.trap            := core.io.trap
    io.redirect        := core.io.redirect
    io.recovering      := core.io.recovering
    io.fetchPc         := core.io.fetchPc
    io.fetchWait       := !hold && !frontend.io.instruction0.valid
    io.msiError        := core.io.msiError
    io.externalPending := core.io.externalPending
    io.committedValue  := core.io.committedValue
}
