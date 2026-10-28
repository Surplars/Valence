package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.bus.tilelink.TLParams
import soc.core.ooo._
import soc.ip.bus.RegisterPort
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Real registered request/return chain. Authority inputs have the same bounded
  * MemoryOperation contract as BoundHeadStoreOverlapGsim; this is not a ROB test.
  * The host owns full-token, VA/PA, bytes, accepted-handle and cancellation oracles.
  * Only external protocol stalls and ordinary peripheral/PTE/backing replies are driven.
  */
class PostedFrozenOverlapChainGsim(overlap: Boolean) extends Module {
    val profile = ThreeProofRowNativeProfile.config
    val p = profile.coreParams
    private val base = profile.ramBase
    private val bytes = profile.ddrBytes
    private val cfg = profile.cache
    require(profile.productArity == 95 && p.productArity == 178)
    require(profile.dataCacheLines == 512 && profile.cacheWays == 2 &&
        p.memoryEntries == 4 && p.cpuReturnConfig.contains(CpuReturnConfig(4, 2, true)))
    require(profile.registerProbeLookup && profile.tags.compact && profile.tags.bankedStorage)
    // Core proof config is shape-only; MachinePlatform supplies enabled physical geometry.
    require(p.postedStoreMerge && p.sharedMemoryAddressState &&
        p.postedProofConfig.exists(c => c.tokenTagBits == 64 && c.tokenIndexBits == 4))
    // Match the production factory's reviewed shared-write-data eligibility before
    // selecting the candidate constructor. Do not silently force an ineligible profile.
    private val reviewed = CoherentCacheConcurrency(
        readMshrs = 2, responseEntries = 2, writebackEntries = 2,
        overlapWritebackRefill = true, nextLinePrefetch = true, prefetchCandidateCycles = 16,
        storeNextLinePrefetch = true, storePrefetchMruInsertion = true,
        postedPrefetchCoexistence = true, independentDemandAdmission = true,
        splitPrefetchTracking = true, readPrefetchDirtyRetry = true,
        readPrefetchDemandAdoption = true, readPrefetchStoreHold = true,
        durableReadPrefetchCandidate = true, readPrefetchBehindStore = true,
        internalLineGrant = true, concurrentReadStorePrefetch = true, memoryScheduleOverlap = true)
    require(base == BoardSocConfig.ramBase && bytes == BigInt(2) * 1024 * 1024 * 1024)
    require(cfg.futureHomeWayReservation && cfg.storePrefetchLruVictim &&
        cfg.copy(futureHomeWayReservation = false, storePrefetchLruVictim = false) == reviewed)
    private val postedConfig = p.postedProofConfig.get.copy(enabled = true,
        generationBits = 64, epochBits = 32,
        cacheSets = profile.dataCacheLines / profile.cacheWays, cacheWays = profile.cacheWays,
        readMshrs = cfg.readMshrs, responseEntries = cfg.responseEntries, writebackEntries = cfg.writebackEntries,
        guaranteedBase = base, guaranteedBytes = bytes)
    postedConfig.requireCacheAperture(base, bytes)
    private val coherent = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = cfg.sinkBits)
    private val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val overlapEnabled = Output(Bool())
        val seal = Input(Bool())
        val postedEpoch = Output(UInt(32.W))
        val postedBusy = Output(Bool())
        val postedEpisode = Output(Bool())
        val postedAccepted = Output(Valid(new PostedStoreAcceptance(postedConfig)))
        val postedAcknowledged = Output(Valid(new PostedStoreMember(postedConfig)))
        val postedReleased = Output(Valid(new PostedLineEvent(postedConfig)))
        val sbPostedCompleted = Output(Valid(new PostedStoreToken(postedConfig)))
        val sbInputFire = Output(Bool())
        val sbInputProof = Output(Valid(new PostedStoreProof(postedConfig)))
        val sbOutputFire = Output(Bool())
        val sbOutputProof = Output(Valid(new PostedStoreProof(postedConfig)))
        val checkedProof = Output(Valid(new PostedStoreProof(postedConfig)))
        val canonicalChecked = Output(Valid(new CanonicalStoreCertificate(p)))
        val victimRead = Output(Bool())
        val victimCapture = Output(Bool())
        val victimQueued = Output(Bool())
        val pfAllocated = Output(Bool())
        val pfAddress = Output(UInt(64.W))
        val checkedOffer = Output(Bool())
        val start = Flipped(Decoupled(new MemoryOperation(p)))
        val parallel = Input(Bool())
        val qualified = Input(Bool())
        val cancel = Input(UInt(4.W))
        val complete = Decoupled(new BackendCompletion(p))
        val live = Output(UInt(4.W))
        val owner0 = Output(new RobToken(p)); val owner1 = Output(new RobToken(p))
        val owner2 = Output(new RobToken(p)); val owner3 = Output(new RobToken(p))
        val chosen = Output(UInt(2.W))
        val overlapAccepted = Output(Bool())
        val discarded = Output(Bool())
        val epoch = Output(UInt(32.W)); val stable = Output(Bool())
        val vm = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W)); val pmpAddress = Input(UInt(54.W))
        val precheckFlush = Input(Bool())
        val pte = new SvPteReadPort
        val mmio0 = new RegisterPort; val mmio1 = new RegisterPort
        val dma = Flipped(new DataPort)
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val holdQueue = Input(Bool())
        val holdEnqueue = Input(Bool())
        val holdCacheRequest = Input(Bool())
        val holdCacheResponse = Input(Bool())
        val queueFire = Output(Bool())
        val queueOwner = Output(new RobToken(p))
        val queueHandle = Output(UInt(3.W))
        val queueAddress = Output(UInt(64.W))
        val physicalFire = Output(Bool())
        val physical = Output(new DataRequest(p.dataReturnHandleBits))
        val physicalResponseFire = Output(Bool())
        val cacheFire = Output(Bool())
        val cacheRequest = Output(new DataRequest(p.dataReturnHandleBits))
        val cacheHit = Output(Bool())
        val independentStoreWrite = Output(Bool())
        val cacheResponseValid = Output(Bool()); val cacheResponseReady = Output(Bool())
        val cacheResponse = Output(new DataResponse(p.dataReturnHandleBits))
        val lsuResponseFire = Output(Bool())
        val lsuResponse = Output(new DataResponse(p.dataReturnHandleBits))
        val idle = Output(Bool())
        val flushRequest = Input(Bool()); val flushDone = Output(Bool())
    })
    val lsu = Module(new ParallelLoadStoreUnit(p, canonicalHandoff = true, localTaggedResponseReady = p.localTaggedResponseReady))
    val requests = Module(new RegisteredRequestQueue(p))
    val stores = Module(new StoreBuffer(p))
    val responses = Module(new DataResponseBuffer(registerPayload = true, registerHead = true,
        returnConfig = p.cpuReturnConfig))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = profile.translationHitFlow, usePublishedPmpChanges = p.pmpChangePublicationEnabled, queuedHeadSelection = p.queuedHeadSelection,
        alignedNextLinePmp = p.alignedNextLinePmp))
    val translation = Module(new SvTranslationService(3, profile.dataTranslationEntries, p.pmpEntries, loadPeek = true))
    val router0 = Module(new ParallelRegisterRouter(Seq(BigInt("1000", 16) -> BigInt(256)),
        bypassMemoryShift = true, returnConfig = p.cpuReturnConfig))
    val router1 = Module(new ParallelRegisterRouter(Seq(BigInt("2000", 16) -> BigInt(256)),
        bypassMemoryShift = true, returnConfig = p.cpuReturnConfig))
    val cache = Module(new NonBlockingCoherentLineCache(base, bytes, 512, coherent, 2, cfg,
        tagConfig = profile.tags, postedConfig = Some(postedConfig), returnConfig = p.cpuReturnConfig,
        registerProbeLookup = true, localReadSelection = true, shareStoreWriteData = true,
        disjointEvictionStoreOverlap = overlap))
    val home = CoherentLineHomeModule.build(coherent, base, bytes, trackedLines = 512,
        trackedWays = 2, acquireEntries = 2, writebackEntries = 2, mixedReadWrite = true,
        tagConfig = profile.tags, dmaLineTransfers = true, dmaLineEntries = 4,
        lineTransferDispatchFlow = true, lineReadChannel = true, internalLineGrant = true,
        memoryScheduleOverlap = true, futureHomeWayReservation = true, allowSharedFutureLookup = true)
    val atomic = Module(new AtomicDataMemory(base, bytes, registerResponseOwners = true))
    val homeRequests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 4),
        axiAddressWidth = 32, axiIdWidth = 4, maxOutstanding = 4, maxBurstBeats = 16,
        maxOutstandingWrites = 2, unorderedResponses = true, axiAddressBase = base, axiWindowBytes = bytes,
        writeCollectionFlow = true, lineReadChannel = true,
        localPayloadWriteEnable = true, localPayloadWriteRow = true))

    lsu.io.start <> io.start
    lsu.io.parallel := io.parallel
    lsu.io.boundHeadStoreOverlapQualified.get := io.qualified
    lsu.io.relaxStoreOwner.get := 0.U.asTypeOf(lsu.io.relaxStoreOwner.get)
    lsu.io.issueDestination.foreach(_ := 0.U.asTypeOf(lsu.io.issueDestination.get))
    lsu.io.cancel := VecInit((0 until 4).map(i => io.cancel(i)))
    lsu.io.fastStoreRetire := false.B; lsu.io.fastLoadRetire := false.B
    io.complete <> lsu.io.complete
    io.live := lsu.io.live.asUInt
    Seq(io.owner0, io.owner1, io.owner2, io.owner3).zipWithIndex.foreach { case (out, i) => out := lsu.io.owner(i) }
    io.chosen := BoringUtils.bore(lsu.chosen)
    io.overlapAccepted := lsu.io.boundHeadStoreOverlapAccepted.get
    io.discarded := lsu.io.discarded
    requests.io.enq <> lsu.io.memory.request
    requests.io.enq.valid := lsu.io.memory.request.valid && !io.holdEnqueue
    lsu.io.memory.request.ready := requests.io.enq.ready && !io.holdEnqueue
    requests.proofIn.get := lsu.io.postedProof.get
    requests.canonicalOriginIn.get := lsu.io.canonicalStoreOrigin.get
    requests.frozenProofIn.get := lsu.io.frozenStoreProof.get
    stores.io.upstream.request <> requests.io.deq
    stores.io.upstream.request.valid := requests.io.deq.valid && !io.holdQueue
    requests.io.deq.ready := stores.io.upstream.request.ready && !io.holdQueue
    stores.io.upstream.request.bits.size := Mux(requests.io.deq.valid, requests.io.deq.bits.size, 0.U)
    stores.io.upstreamCanonicalStoreOrigin.get := requests.canonicalOriginOut.get
    stores.io.upstreamCanonicalStoreOrigin.get.valid := stores.io.upstream.request.valid && requests.canonicalOriginOut.get.valid
    stores.io.upstreamFrozenStoreProof.get := requests.frozenProofOut.get
    stores.io.upstreamFrozenStoreProof.get.valid := stores.io.upstream.request.valid && requests.frozenProofOut.get.valid
    lsu.io.memory.response <> stores.io.upstream.response
    stores.io.fastStore.valid := false.B; stores.io.fastStore.bits := 0.U.asTypeOf(stores.io.fastStore.bits)
    stores.io.upstreamProof.get := requests.proofOut.get
    stores.io.fastProof.get := 0.U.asTypeOf(stores.io.fastProof.get)
    stores.io.externalPostedBusy.get := cache.io.posted.get.busy
    responses.io.upstream <> stores.io.memory
    adapter.io.virtual <> responses.io.downstream
    adapter.io.canonicalStoreOrigin.get := stores.io.memoryCanonicalStoreOrigin.get
    adapter.io.frozenStoreProof.get := stores.io.memoryFrozenStoreProof.get
    adapter.io.vmState := io.vm
    val pmp = PendingStoreProofFixture.pmp(io.pmpCfg, io.pmpAddress)
    // Test-boundary CSR-state publication: changes are identified independently
    // from the host's raw PMP state, never from a permission outcome.
    val previousPmp = RegNext(pmp.asUInt)
    adapter.io.pmpRawChanged.get := previousPmp =/= pmp.asUInt
    adapter.io.pmpState := pmp; translation.io.pmpState := pmp
    translation.io.client <> adapter.io.translation
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    adapter.io.precheckFlush.get := io.precheckFlush
    translation.io.flush := io.precheckFlush
    adapter.io.loadPrecheck.get.request.valid := false.B
    adapter.io.loadPrecheck.get.request.bits := 0.U.asTypeOf(adapter.io.loadPrecheck.get.request.bits)
    io.pte <> translation.io.memory
    io.epoch := adapter.io.loadPrecheck.get.epoch; io.stable := adapter.io.loadPrecheck.get.stable
    router0.io.upstream <> adapter.io.physical
    router1.io.upstream <> router0.io.memory
    io.mmio0 <> router0.io.registers(0); io.mmio1 <> router1.io.registers(0)
    cache.io.upstream <> router1.io.memory
    cache.io.upstream.request.valid := router1.io.memory.request.valid && !io.holdCacheRequest
    router1.io.memory.request.ready := cache.io.upstream.request.ready && !io.holdCacheRequest
    router1.io.memory.response.valid := cache.io.upstream.response.valid && !io.holdCacheResponse
    cache.io.upstream.response.ready := router1.io.memory.response.ready && !io.holdCacheResponse
    atomic.io.cpu <> cache.io.downstream; atomic.io.dma <> io.dma; atomic.io.clearReservation := false.B
    homeRequests.io.upstream <> atomic.io.memory; homeRequests.io.requestCpu := atomic.io.memoryRequestCpu
    home.io.upstream <> homeRequests.io.downstream; home.io.upstreamRequestCpu := homeRequests.io.downstreamRequestCpu
    home.io.clients(0) <> cache.io.tl
    cache.io.lineGrant.get <> home.io.lineGrants.get(0)
    home.io.dmaLine.get.request.valid := false.B
    home.io.dmaLine.get.request.bits := 0.U.asTypeOf(home.io.dmaLine.get.request.bits)
    home.io.dmaLine.get.response.ready := true.B
    ordered.io.data <> home.io.downstream
    arbiter.io.masters(0) <> ordered.io.tl
    CoherentHomeUlBoundary.connect(home.io.line, arbiter.io.masters(1))
    ddr.io.lineRead.get <> home.io.lineRead.get
    ddr.io.tl <> arbiter.io.manager; io.ddrAxi <> ddr.io.axi
    cache.io.flushRequest := io.flushRequest
    home.io.drainRequest := io.flushRequest && cache.io.flushDone
    io.flushDone := cache.io.flushDone && home.io.drainDone
    io.idle := !lsu.io.busy && !stores.io.busy && responses.io.idle && adapter.io.idle && translation.io.idle &&
        !requests.io.deq.valid
    val cachePosted = cache.io.posted.get
    val transport = adapter.io.posted.get
    transport.upstreamProof := stores.io.memoryProof.get
    transport.externalBusy := cachePosted.busy
    val drained = !lsu.io.busy && !stores.io.busy && responses.io.idle && adapter.io.idle &&
        !requests.io.deq.valid && !cachePosted.busy
    transport.aggregateDrained := drained && !io.start.valid
    cachePosted.contextEpoch := transport.contextEpoch
    cachePosted.requestProof := transport.requestProof
    cachePosted.requestProof.valid := cache.io.upstream.request.valid && transport.requestProof.valid
    cachePosted.seal := io.seal || io.flushRequest || transport.contextChanging
    cachePosted.endEpisode := drained && !io.start.valid && !transport.requestProof.valid
    io.idle := drained && translation.io.idle && !cache.io.prefetchBusy
    io.overlapEnabled := overlap.B
    io.postedEpoch := transport.contextEpoch
    io.postedBusy := cachePosted.busy
    io.postedEpisode := cachePosted.episodeActive
    val postedObs = BoringUtils.bore(cache.observationPosted.get)
    io.postedAccepted := postedObs.accepted
    io.postedAcknowledged := postedObs.acknowledged
    io.postedReleased := postedObs.released
    io.sbPostedCompleted := stores.io.postedCompleted.get
    io.sbInputFire := stores.io.upstream.request.fire
    io.sbInputProof := stores.io.upstreamProof.get
    io.sbOutputFire := stores.io.memory.request.fire
    io.sbOutputProof := stores.io.memoryProof.get
    io.checkedProof := transport.requestProof
    io.canonicalChecked := adapter.io.canonicalStoreCertificate.get
    val obs = BoringUtils.bore(cache.observationStorePrefetch)
    io.victimRead := obs.wbCapture && obs.wbCaptureDirty
    io.victimCapture := RegNext(obs.wbCapture && obs.wbCaptureDirty, false.B)
    io.victimQueued := obs.wbCapture && !obs.wbCaptureDirect
    io.pfAllocated := obs.allocated
    io.pfAddress := obs.allocatedAddress
    io.checkedOffer := cache.io.upstream.request.valid
    def heldRequest(port: DecoupledIO[DataRequest]): Unit = {
        val held = RegNext(port.valid && !port.ready, false.B)
        val saved = RegEnable(port.bits, port.valid && !port.ready)
        when(held) { assert(port.valid && port.bits.asUInt === saved.asUInt, "test boundary withdrew held request") }
    }
    heldRequest(requests.io.enq)
    heldRequest(stores.io.upstream.request)
    heldRequest(cache.io.upstream.request)
    CpuReturnTransport.held(router1.io.memory.response)
    io.queueFire := requests.io.enq.fire
    io.queueOwner := lsu.io.requestOwner.bits
    io.queueHandle := requests.io.enq.bits.returnHandle.getOrElse(0.U)
    io.queueAddress := requests.io.enq.bits.address
    io.physicalFire := adapter.io.physical.request.fire; io.physical := adapter.io.physical.request.bits
    io.physicalResponseFire := adapter.io.physical.response.fire
    io.cacheFire := cache.io.upstream.request.fire; io.cacheRequest := cache.io.upstream.request.bits
    io.cacheHit := cache.io.hit
    val independentDemand = BoringUtils.bore(cache.asInstanceOf[NonBlockingCoherentLineCache].observationIndependentDemand)
    io.independentStoreWrite := independentDemand(2)
    io.cacheResponseValid := cache.io.upstream.response.valid
    io.cacheResponseReady := cache.io.upstream.response.ready
    io.cacheResponse := cache.io.upstream.response.bits
    io.lsuResponseFire := lsu.io.memory.response.fire; io.lsuResponse := lsu.io.memory.response.bits
}
object PostedFrozenOverlapChainGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new PostedFrozenOverlapChainGsim(args(1) == "1"), Array("--target-dir", args.head))
}
