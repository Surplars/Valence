package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.uart.UartConsole
import soc.ip.dma.MemoryCopyDma
import soc.ip.timer.MachineTimer
import soc.ip.memory.CacheStallEvents
import soc.ip.tilelink.{TwoBankTileLinkRouter, TwoMasterTileLinkArbiter, TwoMasterTwoBankTileLinkCrossbar}
import soc.bus.tilelink.TLParams

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
    ramBytes: Int = 4096,
    translationService: Boolean = false,
    translationLevels: Int = 4,
    pteCacheEntries: Int = 8,
    coreDataTranslation: Boolean = false,
    coreInstructionTranslation: Boolean = false,
    ramInitFile: String = ""
) extends Module {
    require(Set(2, 4).contains(p.renameWidth) && p.speculativeRamBase == BigInt("80010000", 16) &&
        p.speculativeRamBytes == ramBytes)
    require(ramBytes >= 4096 && ramBytes <= (1 << 26) && isPow2(ramBytes))
    require(romWords >= 4 && romWords <= 16384 && isPow2(romWords))
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
    require(coherentLineCacheLines == 0 || (coherentLineCache && coherentLineCacheLines >= 2 &&
        coherentLineCacheLines <= ramBytes / 64 && isPow2(coherentLineCacheLines)))
    private val fetchWords = if (p.compressedInstructions && p.renameWidth == 4) 4 else 2
    val io = IO(new Bundle {
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
        val ramProgram = if (programmable && translationService) Some(Input(new Bundle {
            val write = Bool()
            val index = UInt(log2Ceil(ramBytes / 8).W)
            val data = UInt(64.W)
        })) else None
    })
    val hold       = io.program.map(_.hold).getOrElse(false.B)
    val core       = Module(new MappedMachineCore(p.copy(machineSystem = true, atomicMemory = true,
        pmpEntries = 16, virtualMemoryLevels = if (translationService) translationLevels else 0),
        dataTranslation = coreDataTranslation))
    val frontend   = Module(new SynchronousFetch(16, p.compressedInstructions, p.frontendCacheSets,
        p.renameWidth))
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
    val physicalFetch = fetchAdapter.map(_.io.physical).getOrElse(frontend.io.memory)
    val lineFetchIdle = WireDefault(true.B)
    val rom        = Module(new InstructionRom(romWords, BigInt("80000000", 16), romFiles, programmable))
    val ram        = Module(new SynchronousDataRam(bytes = if (splitTileLinkMemory) 2048 else ramBytes,
        initFile = ramInitFile, responseDelay = ramResponseDelay,
        programmable = programmable && translationService))
    val secondRam = if (splitTileLinkMemory) {
        Some(Module(new SynchronousDataRam(bytes = 2048, base = BigInt("80010800", 16),
            responseDelay = ramResponseDelay)))
    } else None
    val uart       = Module(new UartConsole())
    val uartRouter = Module(new CoreRegisterRouter(BigInt("10000000", 16), bytes = 8))
    uartRouter.io.registers <> uart.io.mmio
    uart.io.rx := io.uartRx
    io.uartTx  := uart.io.tx
    val timer       = Module(new MachineTimer())
    val timerRouter = Module(new CoreRegisterRouter(BigInt("02000000", 16), bytes = 65536))
    timerRouter.io.upstream <> core.io.memory
    timerRouter.io.registers <> timer.io.mmio
    timer.io.tick          := io.timerTick
    core.io.timerInterrupt := timer.io.irq
    core.io.timeValue      := timer.io.timeValue
    uartRouter.io.upstream <> timerRouter.io.memory
    val dma       = Module(new MemoryCopyDma())
    val dmaRouter = Module(new CoreRegisterRouter(BigInt("10001000", 16), bytes = 40))
    val shared    = Module(new AtomicDataMemory(bytes = ramBytes))
    val privateCacheLines = if (coherentLineCacheLines == 0) (ramBytes / 64).min(128)
        else coherentLineCacheLines
    val privateCache = if (coherentLineCache) Some(Module(new CoherentLineCache(
        bytes = ramBytes, lines = privateCacheLines))) else None
    dmaRouter.io.upstream <> uartRouter.io.memory
    dmaRouter.io.registers <> dma.io.control
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
            cache.io.upstream <> dmaRouter.io.memory
            shared.io.cpu <> cache.io.downstream
        case None =>
            core.io.fenceIFlushReady := true.B
            shared.io.cpu <> dmaRouter.io.memory
    }
    shared.io.dma.request.valid        := dma.io.memory.request.valid
    shared.io.dma.request.bits.address := dma.io.memory.request.bits.address
    shared.io.dma.request.bits.data    := dma.io.memory.request.bits.data
    shared.io.dma.request.bits.write   := dma.io.memory.request.bits.write
    shared.io.dma.request.bits.size    := dma.io.memory.request.bits.size
    shared.io.dma.request.bits.mask    := dma.io.memory.request.bits.byteEnable
    dma.io.memory.request.ready        := shared.io.dma.request.ready
    dma.io.memory.response.valid       := shared.io.dma.response.valid
    dma.io.memory.response.bits.data   := shared.io.dma.response.bits.data
    dma.io.memory.response.bits.error  := shared.io.dma.response.bits.error
    shared.io.dma.response.ready       := dma.io.memory.response.ready
    io.activity.foreach { activity =>
        activity.dmaActive     := dma.io.active
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
    for (module <- Seq(core, frontend, rom, ram, uart, uartRouter, dma, dmaRouter, shared, timer, timerRouter) ++
        secondRam.toSeq) {
        module.reset := reset.asBool || hold
    }
    io.program.foreach { program =>
        rom.io.write.get.valid      := program.write && program.hold
        rom.io.write.get.bits.index := program.index
        rom.io.write.get.bits.data  := program.data
        when(program.write) { assert(program.hold, "program ROM only with the platform held in reset") }
    }
    io.ramProgram.foreach { program =>
        ram.io.program.get.valid := program.write && hold
        ram.io.program.get.bits.index := program.index
        ram.io.program.get.bits.data := program.data
        when(program.write) { assert(hold, "program RAM only with the platform held in reset") }
    }
    val downstream = if (sharedReadCache) {
        val cache = Module(new CachedDataMemory(sharedReadCacheLines, p.speculativeRamBytes))
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
        val systemArbiter = Module(new SharedDataArbiter)
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
    val (ramUpstream, secondRamUpstream) = if (tileLinkMemory) {
        val bridge = Module(new OrderedTileLinkBridge(
            orderedWrites = !splitTileLinkMemory,
            orderedMixedAccesses = !splitTileLinkMemory,
            orderedWriteBankBase = p.speculativeRamBase,
            orderedWriteBankBytes = if (splitTileLinkMemory) 2048 else 0,
            allowWriteErrors = true,
            flowHeadResponse = p.flowTileLinkResponse))
        bridge.reset := reset.asBool || hold
        val coherentHome = privateCache.map { cache =>
            val home = Module(new CoherentLineHome(bytes = ramBytes,
                trackedLines = if (privateCacheLines < ramBytes / 64) privateCacheLines else 0))
            home.reset := reset.asBool || hold
            home.io.upstream <> physicalData
            home.io.upstreamRequestCpu := physicalDataRequestCpu
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
        if (coherentHome.isEmpty) { bridge.io.data <> physicalData }
        if (tileLinkFetch) {
            val upstreamParams = TLParams(addrWidth = 64, dataWidth = 64,
                sourceBits = if (coherentLineCache) 4 else 3)
            val managerParams = upstreamParams.copy(sourceBits = upstreamParams.sourceBits + 1)
            val crossbar = Module(new TwoMasterTwoBankTileLinkCrossbar(upstreamParams,
                secondBankBytes = ramBytes))
            val romManager = Module(new TileLinkInstructionRomAdapter(romWords, params = managerParams))
            for (module <- Seq(crossbar, romManager)) {
                module.reset := reset.asBool || hold
            }
            if (instructionLineCacheLines > 0) {
                val fetchCache = Module(new InstructionLineCache(upstreamParams,
                    ramBase = p.speculativeRamBase, ramBytes = ramBytes,
                    romBytes = romWords * 4, lines = instructionLineCacheLines,
                    packetWords = fetchWords, prefetchEnabled = fetchWords == 4))
                fetchCache.reset := reset.asBool || hold
                physicalFetch <> fetchCache.io.fetch
                fetchCache.io.tl <> crossbar.io.masters(1)
                fetchCache.io.pmpState := core.io.pmpState.get
                fetchCache.io.privilege := core.io.fetchPrivilege.get
                fetchCache.io.invalidate := core.io.invalidateFetch
                lineFetchIdle := fetchCache.io.idle
            } else {
                val fetchBridge = Module(new InstructionTileLinkBridge(upstreamParams,
                    immutableBytes = romWords * 4))
                fetchBridge.reset := reset.asBool || hold
                if (fetchWords == 4) {
                    val adapter = Module(new WideInstructionAdapter)
                    adapter.reset := reset.asBool || hold
                    physicalFetch <> adapter.io.wide
                    adapter.io.narrow <> fetchBridge.io.fetch
                } else physicalFetch <> fetchBridge.io.fetch
                fetchBridge.io.tl <> crossbar.io.masters(1)
            }
            io.activity.foreach { activity =>
                activity.fetchGetFire := crossbar.io.masters(1).a.fire
                activity.fetchGetAddress := crossbar.io.masters(1).a.bits.address
                activity.fetchGetSize := crossbar.io.masters(1).a.bits.size
            }
            coherentHome match {
                case Some(home) =>
                    val arbiter = Module(new TwoMasterTileLinkArbiter(
                        TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)))
                    arbiter.reset := reset.asBool || hold
                    bridge.io.tl <> arbiter.io.masters(0)
                    home.io.line <> arbiter.io.masters(1)
                    arbiter.io.manager <> crossbar.io.masters(0)
                case None => bridge.io.tl <> crossbar.io.masters(0)
            }
            crossbar.io.banks(0) <> romManager.io.tl
            romManager.io.rom <> rom.io.fetch
            if (splitTileLinkMemory) {
                val router = Module(new TwoBankTileLinkRouter(managerParams))
                val banks = (0 until 2).map(i => Module(new TileLinkDataRamAdapter(
                    params = managerParams, burstEnabled = true,
                    burstBase = p.speculativeRamBase + i * 2048, burstBytes = 2048)))
                router.reset := reset.asBool || hold
                banks.foreach(_.reset := reset.asBool || hold)
                crossbar.io.banks(1) <> router.io.host
                for (i <- 0 until 2) { router.io.banks(i) <> banks(i).io.tl }
                (banks.head.io.memory, Some(banks(1).io.memory))
            } else {
                val manager = Module(new TileLinkDataRamAdapter(params = managerParams,
                    burstEnabled = true, burstBase = p.speculativeRamBase, burstBytes = ramBytes))
                manager.reset := reset.asBool || hold
                crossbar.io.banks(1) <> manager.io.tl
                (manager.io.memory, None)
            }
        } else if (splitTileLinkMemory) {
            val router = Module(new TwoBankTileLinkRouter)
            val banks = (0 until 2).map(i => Module(new TileLinkDataRamAdapter(
                burstEnabled = true, burstBase = p.speculativeRamBase + i * 2048,
                burstBytes = 2048)))
            router.reset := reset.asBool || hold
            banks.foreach(_.reset := reset.asBool || hold)
            bridge.io.tl <> router.io.host
            for (i <- 0 until 2) { router.io.banks(i) <> banks(i).io.tl }
            (banks.head.io.memory, Some(banks(1).io.memory))
        } else {
            val manager = Module(new TileLinkDataRamAdapter(
                burstEnabled = true, burstBase = p.speculativeRamBase, burstBytes = ramBytes))
            manager.reset := reset.asBool || hold
            bridge.io.tl <> manager.io.tl
            (manager.io.memory, None)
        }
    } else (physicalData, None)
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
    core.io.sources            := io.sources | (uart.io.irq.asUInt << 2) | (dma.io.irq.asUInt << 3)
    core.io.inspectRegister    := io.inspectRegister
    ram.io.port.request.valid  := ramUpstream.request.valid && !hold
    ram.io.port.request.bits   := ramUpstream.request.bits
    ramUpstream.request.ready   := ram.io.port.request.ready && !hold
    ramUpstream.response.valid  := ram.io.port.response.valid && !hold
    ramUpstream.response.bits   := ram.io.port.response.bits
    ram.io.port.response.ready := ramUpstream.response.ready && !hold
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
        activity.ramRequestStall  := (ram.io.port.request.valid && !ram.io.port.request.ready) || extraRequestStall
        activity.ramResponseStall := (ram.io.port.response.valid && !ram.io.port.response.ready) || extraResponseStall
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
