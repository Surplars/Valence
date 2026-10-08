package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.core.ooo.{BoardSocConfig, BoardSocTop, DdrBridgeConfig, CoherentCacheConcurrency, CacheTagConfig, FpgaStorageConfig}

/** Avoid exposing a Vec at the GSIM top boundary (the pinned generator needs scalar accessors). */
class BoardSocGsim(externalDdr: Boolean = false, clockHz: Int = 40000000,
    timingProfile: String = BoardSocConfig.timingProfile, uartBaud: Int = 1500000,
    dataCacheWays: Int = BoardSocConfig.dataCacheWays,
    issueWidth: Int = BoardSocConfig.issueWidth, instructionPrefetch: Boolean = true,
    isaProfile: String = BoardSocConfig.isaProfile,
    ddrMemoryBytes: BigInt = BoardSocConfig.ddrBytes, frontendProbes: Boolean = false,
    instructionLineCacheLines: Int = 8, backendProbes: Boolean = false, dataCacheLines: Int = 32,
    ddrBridge: DdrBridgeConfig = BoardSocConfig.ddrBridge,
    cacheConcurrency: CoherentCacheConcurrency = CoherentCacheConcurrency(),
    loadIssueForwarding: Option[Boolean] = None,
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
    identityDataFlow: Boolean = false,
    fpgaStorage: FpgaStorageConfig = FpgaStorageConfig.Registers,
    virtualRamLoadPrecheck: Boolean = false) extends Module {
    private val board = Module(new BoardSocTop(vivadoMemories = false, simulation = true,
        externalDdr = externalDdr, socClockHz = clockHz, timingProfile = timingProfile, uartBaud = uartBaud,
        dataCacheWays = dataCacheWays, issueWidth = issueWidth, instructionPrefetch = instructionPrefetch,
        isaProfile = isaProfile, ddrMemoryBytes = ddrMemoryBytes, instructionLineCacheLines = instructionLineCacheLines,
        dataCacheLines = dataCacheLines, ddrBridge = ddrBridge, cacheConcurrency = cacheConcurrency, loadIssueForwarding = loadIssueForwarding, tagConfig = tagConfig, identityDataFlow = identityDataFlow, fpgaStorage = fpgaStorage,
        virtualRamLoadPrecheck = virtualRamLoadPrecheck))
    val io = IO(new Bundle {
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val program = Input(chiselTypeOf(board.io.program.get))
        val ramProgram = Input(new Bundle {
            val write = Bool()
            val index = UInt(17.W)
            val data = UInt(64.W)
        })
        val ddrReady = Input(Bool())
        val ddrAxi = if (externalDdr) Some(new soc.ip.axi.Axi4MemoryPort(32, ddrBridge.axiIdWidth)) else None
        val trap = Output(chiselTypeOf(board.io.trap.get))
        val commit0 = Output(Bool())
        val commit0Pc = Output(UInt(64.W))
        val commit1 = Output(Bool())
        val commit1Pc = Output(UInt(64.W))
        val fetchPc = Output(UInt(64.W))
        val cacheProfile = Output(new soc.core.ooo.CoherentCacheProfile)
        val headProfile = Output(new soc.core.ooo.HeadProfile)
    })
    board.io.uartRx := io.uartRx
    board.io.program.get := io.program
    board.io.ramProgram.foreach(_ := io.ramProgram)
    if (externalDdr) {
        board.io.ddrReady.get := io.ddrReady
        io.ddrAxi.get <> board.io.ddrAxi.get
    }
    io.uartTx := board.io.uartTx
    io.trap := board.io.trap.get
    io.commit0 := board.io.commit.get(0).valid
    io.commit0Pc := board.io.commit.get(0).bits.pc
    io.commit1 := board.io.commit.get(1).valid
    io.commit1Pc := board.io.commit.get(1).bits.pc
    io.fetchPc := board.io.fetchPc.get
    io.cacheProfile := board.io.cacheProfile.get
    io.headProfile := board.io.headProfile.get

    // Capacity experiment only: scalar leaf taps preserve production interfaces and avoid
    // dynamic BoringUtils vector reads in the pinned generator. Old ledgers stay two-slot.
    val memoryLiveSlots = IO(Output(UInt(4.W)))
    if (timingProfile == BoardSocConfig.memoryCapacityProfile) {
        val slots = board.platform.core.core.core.backend.lsu.slots
        memoryLiveSlots := PopCount(slots.map(slot => BoringUtils.bore(slot.io.busy)))
    } else {
        memoryLiveSlots := 0.U
    }

    // Optional passive owner-qualified backend probes. Index and 64-bit tag remain separate.
    val backendEvents = IO(Output(UInt(48.W)))
    val backendHeadTag = IO(Output(UInt(64.W)))
    val backendHeadIndex = IO(Output(UInt(8.W)))
    val backendQueueHeadIndex = IO(Output(UInt(8.W)))
    val backendQueueHeadTag = IO(Output(UInt(64.W)))
    val backendRequestTag = IO(Output(UInt(64.W)))
    val backendRequestIndex = IO(Output(UInt(8.W)))
    val backendStartTag = IO(Output(UInt(64.W)))
    val backendStartIndex = IO(Output(UInt(8.W)))
    val backendCompleteTag = IO(Output(UInt(64.W)))
    val backendCompleteIndex = IO(Output(UInt(8.W)))
    val backendSlot0Tag = IO(Output(UInt(64.W)))
    val backendSlot1Tag = IO(Output(UInt(64.W)))
    val backendSlotIndices = IO(Output(UInt(16.W)))
    val backendSlotState = IO(Output(UInt(16.W)))
    val backendReturnSlot = IO(Output(UInt(2.W)))
    val backendFifoCount = IO(Output(UInt(4.W)))
    val backendStoreCause = IO(Output(UInt(3.W)))
    val backendReset = IO(Output(Bool()))
    // Full scalar fingerprints for passive physical data-path ownership, never dynamic vector taps.
    val dataPathEvents = IO(Output(UInt(48.W)))
    val dataPathCounts = IO(Output(UInt(64.W)))
    val dataPathRequest0Address = IO(Output(UInt(64.W)))
    val dataPathRequest0Data = IO(Output(UInt(64.W)))
    val dataPathRequest0Meta = IO(Output(UInt(64.W)))
    val dataPathRequest1Address = IO(Output(UInt(64.W)))
    val dataPathRequest1Data = IO(Output(UInt(64.W)))
    val dataPathRequest1Meta = IO(Output(UInt(64.W)))
    val dataPathRequest2Address = IO(Output(UInt(64.W)))
    val dataPathRequest2Data = IO(Output(UInt(64.W)))
    val dataPathRequest2Meta = IO(Output(UInt(64.W)))
    val dataPathRequest3Address = IO(Output(UInt(64.W)))
    val dataPathRequest3Data = IO(Output(UInt(64.W)))
    val dataPathRequest3Meta = IO(Output(UInt(64.W)))
    val dataPathRequest4Address = IO(Output(UInt(64.W)))
    val dataPathRequest4Data = IO(Output(UInt(64.W)))
    val dataPathRequest4Meta = IO(Output(UInt(64.W)))
    val dataPathRequest5Address = IO(Output(UInt(64.W)))
    val dataPathRequest5Data = IO(Output(UInt(64.W)))
    val dataPathRequest5Meta = IO(Output(UInt(64.W)))
    val dataPathRequest6Address = IO(Output(UInt(64.W)))
    val dataPathRequest6Data = IO(Output(UInt(64.W)))
    val dataPathRequest6Meta = IO(Output(UInt(64.W)))
    val dataPathRequest7Address = IO(Output(UInt(64.W)))
    val dataPathRequest7Data = IO(Output(UInt(64.W)))
    val dataPathRequest7Meta = IO(Output(UInt(64.W)))
    val dataPathRequest8Address = IO(Output(UInt(64.W)))
    val dataPathRequest8Data = IO(Output(UInt(64.W)))
    val dataPathRequest8Meta = IO(Output(UInt(64.W)))
    val dataPathRequest9Address = IO(Output(UInt(64.W)))
    val dataPathRequest9Data = IO(Output(UInt(64.W)))
    val dataPathRequest9Meta = IO(Output(UInt(64.W)))
    val dataPathReply0Data = IO(Output(UInt(64.W)))
    val dataPathReply0Flags = IO(Output(UInt(64.W)))
    val dataPathReply1Data = IO(Output(UInt(64.W)))
    val dataPathReply1Flags = IO(Output(UInt(64.W)))
    val dataPathReply2Data = IO(Output(UInt(64.W)))
    val dataPathReply2Flags = IO(Output(UInt(64.W)))
    val dataPathReply3Data = IO(Output(UInt(64.W)))
    val dataPathReply3Flags = IO(Output(UInt(64.W)))
    val dataPathReply4Data = IO(Output(UInt(64.W)))
    val dataPathReply4Flags = IO(Output(UInt(64.W)))
    backendReset := reset.asBool
    if (backendProbes) {
        require(frontendProbes && issueWidth == 2)
        val b = board.platform.core.core.core.backend
        val l = b.lsu
        val q = b.observationRequests.get
        val stores = b.observationStores.get
        require(l.slots.size == 2, "backend probes require selected two-slot board")
        def tap[T <: Data](signal: T): T = BoringUtils.bore(signal)
        val h = tap(b.head)
        // Static scalar taps avoid dynamic-array output aliases in the pinned GSIM graph pass.
        def atHead(bits: Seq[Bool]): Bool = Mux1H(bits.zipWithIndex.map { case (bit, i) => (h === i.U) -> bit })
        val memoryReady1 = atHead((0 until 16).map(i => tap(b.ownerReady.get.io.ready1(i))))
        val memoryReady2 = atHead((0 until 16).map(i => tap(b.ownerReady.get.io.ready2(i))))
        val store = tap(b.headRequest.store)
        val atomic = tap(b.headRequest.atomic)
        val saved = atHead((0 until 16).map(i => tap(b.storePrepared(i))))
        val choiceHead = tap(b.memoryChoice.valid) && tap(b.memoryChoice.index) === h
        val headToken = b.ledger.io.headSystem.get.headToken
        backendHeadTag := tap(headToken.tag)
        backendHeadIndex := tap(headToken.index)
        backendQueueHeadTag := tap(b.headRenamed.token.tag)
        backendQueueHeadIndex := tap(b.headRenamed.token.index)
        backendRequestTag := tap(l.io.requestOwner.bits.tag)
        backendRequestIndex := tap(l.io.requestOwner.bits.index)
        backendStartTag := tap(l.io.start.bits.token.tag)
        backendStartIndex := tap(l.io.start.bits.token.index)
        backendCompleteTag := tap(l.io.complete.bits.token.tag)
        backendCompleteIndex := tap(l.io.complete.bits.token.index)
        backendSlot0Tag := tap(l.io.owner(0).tag)
        backendSlot1Tag := tap(l.io.owner(1).tag)
        backendSlotIndices := Cat(tap(l.io.owner(1).index).pad(8), tap(l.io.owner(0).index).pad(8))
        backendSlotState := Cat(0.U(6.W), tap(l.io.cancel).asUInt, tap(l.parallel).asUInt,
            tap(l.io.phase(1)), tap(l.io.phase(0)), tap(l.io.live).asUInt)
        backendReturnSlot := tap(l.owners.io.deq.bits)
        backendFifoCount := tap(q.io.count)
        backendStoreCause := tap(stores.io.requestStallCause)
        val adapter = board.platform.core.observationTranslation.get
        val responses = board.platform.core.observationResponses.get
        val profile = BoardSocConfig.timingParams(timingProfile, issueWidth)
        require(profile.registeredMemoryAddress && profile.earlyRecoveryIssueBlock &&
            profile.registeredTranslationHeads && profile.registeredTranslatedResponses &&
            profile.registeredStoreResponseOwners && issueWidth == 2)
        val incomingQueue = adapter.virtualRequests.get
        val checkedQueue = adapter.checked.get
        def requestMeta(r: soc.core.ooo.DataRequest): UInt = Cat(tap(r.uncached), tap(r.virtualized),
            tap(r.mask), tap(r.size), tap(r.atomicOp), tap(r.atomic), tap(r.write)).pad(64)
        dataPathRequest0Address := tap(q.io.enq.bits.address)
        dataPathRequest0Data := tap(q.io.enq.bits.data)
        dataPathRequest0Meta := requestMeta(q.io.enq.bits)
        dataPathRequest1Address := tap(q.io.deq.bits.address)
        dataPathRequest1Data := tap(q.io.deq.bits.data)
        dataPathRequest1Meta := requestMeta(q.io.deq.bits)
        dataPathRequest2Address := tap(stores.io.fastStore.bits.address)
        dataPathRequest2Data := tap(stores.io.fastStore.bits.data)
        dataPathRequest2Meta := requestMeta(stores.io.fastStore.bits)
        dataPathRequest3Address := tap(stores.io.memory.request.bits.address)
        dataPathRequest3Data := tap(stores.io.memory.request.bits.data)
        dataPathRequest3Meta := requestMeta(stores.io.memory.request.bits)
        dataPathRequest4Address := tap(adapter.io.virtual.request.bits.address)
        dataPathRequest4Data := tap(adapter.io.virtual.request.bits.data)
        dataPathRequest4Meta := requestMeta(adapter.io.virtual.request.bits)
        dataPathRequest5Address := tap(adapter.incoming.bits.address)
        dataPathRequest5Data := tap(adapter.incoming.bits.data)
        dataPathRequest5Meta := requestMeta(adapter.incoming.bits)
        dataPathRequest6Address := tap(adapter.translated.io.enq.bits.request.address)
        dataPathRequest6Data := tap(adapter.translated.io.enq.bits.request.data)
        dataPathRequest6Meta := requestMeta(adapter.translated.io.enq.bits.request)
        dataPathRequest7Address := tap(adapter.translated.io.deq.bits.request.address)
        dataPathRequest7Data := tap(adapter.translated.io.deq.bits.request.data)
        dataPathRequest7Meta := requestMeta(adapter.translated.io.deq.bits.request)
        dataPathRequest8Address := tap(checkedQueue.deq.bits.request.address)
        dataPathRequest8Data := tap(checkedQueue.deq.bits.request.data)
        dataPathRequest8Meta := requestMeta(checkedQueue.deq.bits.request)
        dataPathRequest9Address := tap(adapter.io.physical.request.bits.address)
        dataPathRequest9Data := tap(adapter.io.physical.request.bits.data)
        dataPathRequest9Meta := requestMeta(adapter.io.physical.request.bits)
        dataPathReply0Data := tap(adapter.io.physical.response.bits.data)
        dataPathReply0Flags := Cat(tap(adapter.io.physical.response.bits.pageFault), tap(adapter.io.physical.response.bits.error)).pad(64)
        dataPathReply1Data := tap(adapter.io.virtual.response.bits.data)
        dataPathReply1Flags := Cat(tap(adapter.io.virtual.response.bits.pageFault), tap(adapter.io.virtual.response.bits.error)).pad(64)
        dataPathReply2Data := tap(responses.io.upstream.response.bits.data)
        dataPathReply2Flags := Cat(tap(responses.io.upstream.response.bits.pageFault), tap(responses.io.upstream.response.bits.error)).pad(64)
        dataPathReply3Data := tap(stores.io.memory.response.bits.data)
        dataPathReply3Flags := Cat(tap(stores.io.memory.response.bits.pageFault), tap(stores.io.memory.response.bits.error)).pad(64)
        dataPathReply4Data := tap(stores.io.upstream.response.bits.data)
        dataPathReply4Flags := Cat(tap(stores.io.upstream.response.bits.pageFault), tap(stores.io.upstream.response.bits.error)).pad(64)
        dataPathCounts := Cat(0.U(28.W), tap(responses.responses.count).pad(4),
            tap(adapter.owners.io.count).pad(4), tap(checkedQueue.count).pad(4),
            tap(adapter.translated.io.count).pad(4), tap(incomingQueue.io.count).pad(4),
            tap(stores.reads).pad(4), tap(stores.owners.io.count).pad(4),
            tap(stores.issued).pad(4), tap(stores.count).pad(4))
        // Exact selected-profile duplicate of reserveMemory with only issueAvailable removed.
        // The registered-address profile captures operands before this predicate. The equality
        // is checked by the host on every nonreset sample, including cycles outside the ROI.
        val reserveWithoutCapacity = !tap(b.interruptDrain) && !tap(b.reserveSystem) &&
            !tap(b.olderSystem) && !tap(b.fpMemoryEpoch) && !tap(b.contextMemoryEpoch) &&
            tap(b.memoryChoice.valid) &&
            tap(b.io.commitEnable) && !tap(b.ledger.io.recovering) &&
            (!tap(b.memoryEntry.request.atomic) || !tap(b.io.memoryBusy)) &&
            (tap(b.memoryChoice.index) === h || (tap(b.speculative) && !tap(b.blockedByStore)))
        val launchWithoutCapacity = reserveWithoutCapacity && !tap(b.earlyRecoveryIssueBlock) &&
            !tap(b.ledger.io.pendingException.valid)
        val younger = tap(b.memoryChoice.index) =/= h && !tap(b.memoryEntry.request.store) &&
            !tap(b.memoryEntry.request.atomic)
        val capacityCandidate = launchWithoutCapacity && younger && tap(l.noOtherSerial) &&
            (tap(l.io.parallel) || tap(l.othersIdle))
        dataPathEvents := VecInit(Seq(
            tap(stores.io.memory.request.valid) && tap(stores.io.memory.request.ready),
            tap(stores.io.memory.response.valid) && tap(stores.io.memory.response.ready),
            tap(stores.drainRequest), tap(stores.flowBufferedWrite), tap(stores.flowFastWrite),
            tap(stores.owners.io.deq.valid), tap(stores.owners.io.deq.bits),
            tap(stores.enqueue), tap(stores.io.forwarded), tap(stores.fastEnqueue),
            tap(b.fpMemoryEpoch) && tap(b.io.memory.request.valid) && tap(b.io.memory.request.ready),
            tap(b.fpMemoryEpoch) && tap(b.io.memory.response.valid) && tap(b.io.memory.response.ready),
            tap(adapter.io.virtual.request.valid) && tap(adapter.io.virtual.request.ready),
            tap(adapter.incoming.valid) && tap(adapter.incoming.ready),
            tap(adapter.io.translation.request.valid) && tap(adapter.io.translation.request.ready),
            tap(adapter.io.translation.response.valid) && tap(adapter.io.translation.response.ready),
            tap(adapter.translated.io.enq.valid) && tap(adapter.translated.io.enq.ready),
            tap(adapter.translated.io.deq.valid) && tap(adapter.translated.io.deq.ready),
            tap(checkedQueue.deq.valid) && tap(checkedQueue.deq.ready),
            tap(adapter.io.physical.request.valid) && tap(adapter.io.physical.request.ready),
            tap(adapter.io.virtual.response.valid) && tap(adapter.io.virtual.response.ready),
            tap(adapter.io.physical.response.valid) && tap(adapter.io.physical.response.ready),
            tap(responses.responses.enq.valid) && tap(responses.responses.enq.ready),
            tap(responses.responses.deq.valid) && tap(responses.responses.deq.ready),
            tap(adapter.waiting), tap(adapter.incoming.bits.virtualized), tap(adapter.physicalFault),
            tap(adapter.owners.io.deq.bits.fault), tap(stores.ackValid),
            tap(adapter.fault), tap(adapter.translated.io.deq.bits.pageFault), tap(adapter.physicalPageFault),
            capacityCandidate, capacityCandidate && !tap(l.available),
            tap(l.io.start.valid) && tap(l.io.start.ready) && younger,
            ((reserveWithoutCapacity && tap(l.io.issueAvailable)) === tap(b.reserveMemory)) &&
                ((launchWithoutCapacity && tap(l.io.issueAvailable)) === tap(l.io.start.valid)),
            tap(b.ordinaryRam), tap(b.memoryEntry.request.store), tap(b.memoryEntry.request.atomic), younger,
            tap(b.fpMemoryEpoch), tap(adapter.translated.io.enq.bits.pageFault),
            tap(adapter.translated.io.enq.bits.accessFault)
        )).asUInt
        backendEvents := VecInit(Seq(
            saved || (memoryReady1 && (!(store || atomic) || memoryReady2)),
            atHead(b.memoryCandidates.map(c => tap(c.valid))), choiceHead,
            tap(l.io.start.valid) && tap(l.io.start.ready),
            tap(b.directStoreFire), tap(l.available), tap(l.noOtherSerial), tap(l.othersIdle),
            tap(l.io.parallel), tap(l.io.issueAvailable), tap(l.io.start.ready),
            tap(b.memoryChoice.valid), tap(b.interruptDrain), tap(b.reserveSystem), tap(b.olderSystem),
            tap(b.fpMemoryEpoch), tap(b.io.commitEnable), tap(b.ledger.io.recovering),
            atomic && tap(b.io.memoryBusy), tap(l.io.start.valid),
            tap(q.io.enq.valid), tap(q.io.enq.ready), tap(q.io.deq.valid), tap(q.io.deq.ready),
            tap(l.io.memory.response.valid), tap(l.io.memory.response.ready),
            tap(l.io.complete.valid), tap(l.io.complete.ready), tap(l.owners.io.deq.valid),
            atHead((0 until 16).map(i => tap(b.eligible(i)))), tap(b.headRequest.system), tap(b.headRequest.mulDiv), store, atomic, saved,
            tap(l.io.fastLoadRetire), tap(l.io.forwarded), tap(stores.buffered), tap(stores.forward),
            tap(stores.local), tap(stores.ackValid), tap(l.io.requestOwner.valid),
            tap(l.io.start.bits.forward.valid), tap(stores.io.fastStore.valid) && tap(stores.io.fastStore.ready)
        )).asUInt
    } else {
        dataPathReply4Data := 0.U; dataPathReply4Flags := 0.U
        dataPathEvents := 0.U; dataPathCounts := 0.U
        dataPathRequest0Address := 0.U
        dataPathRequest0Data := 0.U
        dataPathRequest0Meta := 0.U
        dataPathRequest1Address := 0.U
        dataPathRequest1Data := 0.U
        dataPathRequest1Meta := 0.U
        dataPathRequest2Address := 0.U
        dataPathRequest2Data := 0.U
        dataPathRequest2Meta := 0.U
        dataPathRequest3Address := 0.U
        dataPathRequest3Data := 0.U
        dataPathRequest3Meta := 0.U
        dataPathRequest4Address := 0.U
        dataPathRequest4Data := 0.U
        dataPathRequest4Meta := 0.U
        dataPathRequest5Address := 0.U
        dataPathRequest5Data := 0.U
        dataPathRequest5Meta := 0.U
        dataPathRequest6Address := 0.U
        dataPathRequest6Data := 0.U
        dataPathRequest6Meta := 0.U
        dataPathRequest7Address := 0.U
        dataPathRequest7Data := 0.U
        dataPathRequest7Meta := 0.U
        dataPathRequest8Address := 0.U
        dataPathRequest8Data := 0.U
        dataPathRequest8Meta := 0.U
        dataPathRequest9Address := 0.U
        dataPathRequest9Data := 0.U
        dataPathRequest9Meta := 0.U
        dataPathReply0Data := 0.U
        dataPathReply0Flags := 0.U
        dataPathReply1Data := 0.U
        dataPathReply1Flags := 0.U
        dataPathReply2Data := 0.U
        dataPathReply2Flags := 0.U
        dataPathReply3Data := 0.U
        dataPathReply3Flags := 0.U
        backendEvents := 0.U
        backendHeadTag := 0.U; backendHeadIndex := 0.U; backendQueueHeadTag := 0.U; backendQueueHeadIndex := 0.U
        backendRequestTag := 0.U; backendRequestIndex := 0.U
        backendStartTag := 0.U; backendStartIndex := 0.U
        backendCompleteTag := 0.U; backendCompleteIndex := 0.U
        backendSlot0Tag := 0.U; backendSlot1Tag := 0.U
        backendSlotIndices := 0.U; backendSlotState := 0.U; backendReturnSlot := 0.U
        backendFifoCount := 0.U; backendStoreCause := 0.U
    }

    // Test-only passive taps: no production IO or functional logic changes.
    val perfEvents = IO(Output(UInt(48.W)))
    val perfOccupancy = IO(Output(UInt(3.W)))
    val perfSupply = IO(Output(UInt(2.W)))
    val perfCapture = IO(Output(UInt(2.W)))
    val perfRename = IO(Output(UInt(2.W)))
    val perfDiscard = IO(Output(UInt(3.W)))
    val perfTranslationPhase = IO(Output(UInt(3.W)))
    val perfFetchGetSize = IO(Output(UInt(3.W)))
    val perfFetchGetAddress = IO(Output(UInt(64.W)))
    val perfCacheEvents = IO(Output(UInt(16.W)))
    val perfCacheState = IO(Output(UInt(3.W)))
    val perfCacheGetSource = IO(Output(UInt(8.W)))
    if (frontendProbes) {
        require(issueWidth == 2, "frontend probes currently describe two-wide production configuration")
        perfFetchGetSize := BoringUtils.bore(board.platform.io.activity.get.fetchGetSize)
        perfFetchGetAddress := BoringUtils.bore(board.platform.io.activity.get.fetchGetAddress)
        val cache = board.platform.instructionLineCache.get
        def cacheTap[T <: Data](signal: T): T = BoringUtils.bore(signal)
        val cacheAValid = cacheTap(cache.io.tl.a.valid)
        val cacheAReady = cacheTap(cache.io.tl.a.ready)
        perfCacheState := cacheTap(cache.perfState)
        perfCacheGetSource := cacheTap(cache.io.tl.a.bits.source)
        perfCacheEvents := VecInit(Seq(
            cacheTap(cache.perfAcceptedHit), cacheTap(cache.perfAcceptedMiss),
            cacheTap(cache.perfAcceptedFallback), cacheTap(cache.perfDemandRefillRequest),
            cacheTap(cache.perfDemandRefillComplete), cacheTap(cache.perfDemandRefillError),
            cacheTap(cache.perfDemandRefillInstall), cacheTap(cache.perfWaitingRefill),
            cacheTap(cache.perfFallbackActive), cacheTap(cache.perfRetryFallback),
            cacheTap(cache.perfWaitingPrefetch),
            cacheTap(cache.io.fetch.response.valid) && cacheTap(cache.io.fetch.response.ready),
            cacheTap(cache.io.fetch.request.valid) && cacheTap(cache.io.fetch.request.ready),
            cacheAValid && cacheAReady,
            cacheTap(cache.io.tl.d.valid) && cacheTap(cache.io.tl.d.ready),
            cacheAValid && !cacheAReady
        )).asUInt
        val c = board.platform.core.core.core
        val packet = c.fetchPacket.get
        val ledger = c.backend.ledger
        def tap[T <: Data](signal: T): T = BoringUtils.bore(signal)
        val occupancy = tap(packet.io.occupancy)
        val supply = VecInit(packet.io.supply.map(x => tap(x.valid)))
        val captured = VecInit(packet.io.captured.map(tap(_)))
        val consumed = VecInit(packet.io.consume.map(tap(_)))
        val allocate = VecInit(ledger.io.allocate.map(x => tap(x.valid)))
        val renamed = VecInit(ledger.io.renamed.map(x => tap(x.valid)))
        val pause = tap(packet.io.pause)
        val correction = tap(packet.wrongPath)
        val flush = tap(packet.io.flush.valid)
        val recovery = tap(ledger.recoveryCycle)
        val dispatch = tap(ledger.io.dispatchReady)
        val exhausted = tap(ledger.io.tagExhausted)
        val robFull = tap(ledger.io.occupancy) === ledger.p.robEntries.U
        val capacity0 = tap(ledger.faultCandidates.get.io.capacity)(0)
        val capacity1 = tap(ledger.faultCandidates.get.io.capacity)(1)
        val adapter = board.platform.fetchAdapter.get
        val virtualReq = tap(adapter.io.virtual.request.valid)
        val virtualReady = tap(adapter.io.virtual.request.ready)
        val virtualReply = tap(adapter.io.virtual.response.valid)
        val physicalReq = tap(adapter.io.physical.request.valid)
        val physicalReady = tap(adapter.io.physical.request.ready)
        val physicalReply = tap(adapter.io.physical.response.valid)
        val physicalWait = tap(adapter.io.physical.response.ready)
        val translate = tap(adapter.io.translation.response.ready)
        val translationReq = tap(adapter.io.translation.request.valid)
        val translationReady = tap(adapter.io.translation.request.ready)
        val translationReply = tap(adapter.io.translation.response.valid)
        val f = board.platform.frontend
        val supplyCount = PopCount(supply)
        val consumeCount = PopCount(consumed)
        perfOccupancy := occupancy
        perfSupply := supplyCount
        perfCapture := PopCount(captured)
        perfRename := PopCount(renamed)
        perfDiscard := Mux(correction || flush, occupancy - consumeCount, 0.U)
        // Exclusive observed adapter phases; phase 5 means no exposed predicate matched.
        perfTranslationPhase := Mux(virtualReply, 4.U, Mux(virtualReady, 0.U, Mux(translate, 1.U,
            Mux(physicalReq, 2.U, Mux(physicalWait, 3.U, 5.U)))))
        val events = Seq(
            pause, correction, flush, recovery, tap(ledger.io.recovering),
            allocate(0) && !dispatch, allocate(0) && recovery,
            allocate(0) && exhausted, allocate(0) && robFull,
            allocate(0) && !capacity0,
            allocate(1) && renamed(0) && !capacity1,
            occupancy === 4.U && consumeCount > 0.U && supply(0) && !pause && !correction && !flush,
            occupancy === 3.U && consumeCount > 0.U && supplyCount === 2.U && !pause && !correction && !flush,
            supply(0) && !captured(0), supply(0) && !supply(1),
            virtualReq && virtualReady, virtualReq && !virtualReady, virtualReply,
            physicalReq && physicalReady, physicalReq && !physicalReady,
            physicalReply && physicalWait,
            translationReq && translationReady, translationReply && translate,
            translationReq && translationReady && tap(adapter.io.translation.request.bits.mode) === 0.U,
            tap(f.io.pause), tap(f.io.invalidate), !tap(f.io.instruction0.valid),
            tap(c.backend.headTrapAccepted), tap(c.backend.headSystemAccepted),
            tap(c.backend.ordinaryLocalRedirectAccepted) && tap(c.backend.localInclusive),
            tap(c.backend.ordinaryLocalRedirectAccepted) && !tap(c.backend.localInclusive),
            tap(c.backend.externalWins) && tap(ledger.io.recoveryAccepted),
            tap(board.platform.io.activity.get.fetchGetFire),
            allocate(0), renamed(0), tap(ledger.io.freeCount) === 0.U,
            tap(f.io.enable), translate && !translationReply,
            physicalWait && !physicalReply,
            !supply(0) && occupancy === 0.U && !pause && !correction && !flush,
            virtualReply && virtualReq && !virtualReady,
            virtualReq && virtualReady && (tap(adapter.io.vmState.satp)(63, 60) === 0.U ||
                tap(adapter.io.privilege) === 3.U)
        )
        perfEvents := VecInit(events).asUInt
    } else {
        perfEvents := 0.U
        perfOccupancy := 0.U
        perfSupply := 0.U
        perfCapture := 0.U
        perfRename := 0.U
        perfDiscard := 0.U
        perfTranslationPhase := 0.U
        perfFetchGetSize := 0.U
        perfFetchGetAddress := 0.U
        perfCacheEvents := 0.U
        perfCacheState := 0.U
        perfCacheGetSource := 0.U
    }
}

/** Same memory sizes, address map, latency and compact core as the FPGA board. */
object BoardSocGsimMain extends App {
    val virtualRamLoadPrecheck = args.contains("--virtual-ram-load-precheck")
    val boardArgs = args.filterNot(_ == "--virtual-ram-load-precheck")
    val (memoryArgs, mixedMemory) = soc.core.ooo.MixedMemoryConfig.parseArgs(boardArgs)
    val (storageArgs, fpgaStorage) = FpgaStorageConfig.parseArgs(memoryArgs)
    val identityDataFlow = storageArgs.contains("--identity-data-flow")
    val tagConfig = CacheTagConfig(compact = args.contains("--compact-tags"))
    val cli = storageArgs.filterNot(arg => arg == "--compact-tags" || arg == "--identity-data-flow")
    require(cli.length >= 1 && cli.length <= 19,
        "usage: BoardSocGsimMain output-directory [ddr] [clock-hz] " +
            "[baseline|early-issue|queued-memory|registered-response|registered-replay|staged-fabric|staged-control] " +
            "[uart-baud] [cache-ways] " +
            "[issue-width:2|4] [instruction-prefetch:0|1] [isa:rv64imac|rv64imafc|rv64gc] [ddr-memory-bytes] [frontend-probes:0|1] [instruction-line-cache-lines] [backend-probes:0|1] [data-cache-lines] [ddr-read-slots:1|2|4|8] [ddr-burst-beats:8|16] [read-mshrs:1|2|4] [cache-response-entries] [load-issue-forwarding:0|1] [--compact-tags] [--identity-data-flow] [--unordered-ddr-responses] [--data-next-line-prefetch] [--ddr-write-slots=N] [--cache-writebacks=N] [--overlap-writeback-refill] [--banked-rob] [--shared-store-reads] [--lvt-prf] [--virtual-ram-load-precheck]")
    require(cli.lift(18).forall(Set("0", "1").contains), "load issue forwarding must be 0 or 1")
    require(cli.lift(12).forall(Set("0", "1").contains), "backend-probes must be 0 or 1")
    require(cli.lift(10).forall(Set("0", "1").contains), "frontend-probes must be 0 or 1")
    require(cli.lift(7).forall(Set("0", "1").contains), "instruction-prefetch must be 0 or 1")
    val output = Paths.get(cli.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new BoardSocGsim(cli.lift(1).contains("ddr"),
        cli.lift(2).map(_.toInt).getOrElse(40000000),
        cli.lift(3).getOrElse(BoardSocConfig.timingProfile),
        cli.lift(4).map(_.toInt).getOrElse(1500000),
        cli.lift(5).map(_.toInt).getOrElse(BoardSocConfig.dataCacheWays),
        cli.lift(6).map(_.toInt).getOrElse(BoardSocConfig.issueWidth),
        !cli.lift(7).contains("0"),
        cli.lift(8).getOrElse(BoardSocConfig.isaProfile),
        cli.lift(9).map(BigInt(_)).getOrElse(BoardSocConfig.ddrBytes),
        cli.lift(10).contains("1"),
        cli.lift(11).map(_.toInt).getOrElse(8),
        cli.lift(12).contains("1"),
        cli.lift(13).map(_.toInt).getOrElse(32),
        mixedMemory.ddr(DdrBridgeConfig(maxOutstanding = cli.lift(14).map(_.toInt).getOrElse(1),
            maxBurstBeats = cli.lift(15).map(_.toInt).getOrElse(16))),
        mixedMemory.cache(CoherentCacheConcurrency(readMshrs = cli.lift(16).map(_.toInt).getOrElse(1),
            responseEntries = cli.lift(17).map(_.toInt).getOrElse(2))),
        loadIssueForwarding = cli.lift(18).map(_ == "1"),
        tagConfig = tagConfig, identityDataFlow = identityDataFlow, fpgaStorage = fpgaStorage,
        virtualRamLoadPrecheck = virtualRamLoadPrecheck),
        Array("--target-dir", output.toString))
}
