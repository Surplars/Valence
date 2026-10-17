package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLParams, TLOpcode}
import soc.ip.tilelink.TwoMasterTileLinkArbiter
import soc.core.ooo._

/** Actual private cache, Mixed home, DMA/atomic boundary and AXI bridge.
  * Only AXI backing memory and committed-physical authority are fixture premises.
  */
class FullLineCacheGsim(enabled: Boolean, generationBits: Int = 64, wbEntries: Int = 2, collectionCycles: Int = 256, compactMembers: Boolean = false) extends Module {
    require(wbEntries == 2 && generationBits == 64)
    val concurrency = CoherentCacheConcurrency(
        readMshrs = 2,
        responseEntries = 2,
        writebackEntries = 2,
        overlapWritebackRefill = true,
        nextLinePrefetch = true,
        prefetchCandidateCycles = 16,
        prefetchBreakOnStore = false,
        storeNextLinePrefetch = true,
        storePrefetchMruInsertion = true,
        postedPrefetchCoexistence = true,
        storePrefetchLruVictim = true,
        distinctWayRelease = false,
        independentDemandAdmission = true,
        splitPrefetchTracking = true,
        readPrefetchDirtyRetry = true,
        readPrefetchDemandAdoption = true,
        readPrefetchStoreHold = true,
        durableReadPrefetchCandidate = true,
        readPrefetchBehindStore = true,
        internalLineGrant = true,
        concurrentReadStorePrefetch = true,
        memoryScheduleOverlap = true,
        futureHomeWayReservation = true)
    val returns = CpuReturnConfig(4, 2, true)
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3,
        sinkBits = concurrency.sinkBits)
    val c = PostedStoreMergeConfig(enabled = true, tokenTagBits = 64, tokenIndexBits = 4,
        generationBits = generationBits, cacheSets = 256, cacheWays = 2, writebackEntries = wbEntries,
        guaranteedBase = BigInt("80200000", 16), guaranteedBytes = BigInt(2) * 1024 * 1024 * 1024)
    val io = IO(new Bundle {
        val decision = Output(Vec(c.lineEntries, Valid(new B1PostedAcquireDecision(c))))
        val lineGrantValid = Output(Bool())
        val lineGrantReady = Output(Bool())
        val lineGrantBits = Output(new soc.ip.tilelink.LineGrant(params))
        val logicalRead = Output(Bool())
        val logicalReadAddress = Output(UInt(64.W))
        val upstream = Flipped(new DataPort(returns.handleBits))
        val dma = Flipped(new DataPort)
        val dmaLine = Flipped(new soc.ip.dma.DmaLinePort(4))
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val holdAcquire = Input(Bool())
        val holdGrantAck = Input(Bool())
        val holdReleaseAck = Input(Bool())
        val holdCoherentC = Input(Bool())
        val cacheFlushDone = Output(Bool())
        val homeDrainDone = Output(Bool())
        val monAValid = Output(UInt(64.W))
        val monAReady = Output(UInt(64.W))
        val monAOpcode = Output(UInt(64.W))
        val monAParam = Output(UInt(64.W))
        val monASize = Output(UInt(64.W))
        val monASource = Output(UInt(64.W))
        val monAAddress = Output(UInt(64.W))
        val monAMask = Output(UInt(64.W))
        val monAData = Output(UInt(64.W))
        val monACorrupt = Output(UInt(64.W))
        val monBValid = Output(UInt(64.W))
        val monBReady = Output(UInt(64.W))
        val monBOpcode = Output(UInt(64.W))
        val monBParam = Output(UInt(64.W))
        val monBSize = Output(UInt(64.W))
        val monBSource = Output(UInt(64.W))
        val monBAddress = Output(UInt(64.W))
        val monBMask = Output(UInt(64.W))
        val monBData = Output(UInt(64.W))
        val monBCorrupt = Output(UInt(64.W))
        val monCValid = Output(UInt(64.W))
        val monCReady = Output(UInt(64.W))
        val monCOpcode = Output(UInt(64.W))
        val monCParam = Output(UInt(64.W))
        val monCSize = Output(UInt(64.W))
        val monCSource = Output(UInt(64.W))
        val monCAddress = Output(UInt(64.W))
        val monCData = Output(UInt(64.W))
        val monCCorrupt = Output(UInt(64.W))
        val monDValid = Output(UInt(64.W))
        val monDReady = Output(UInt(64.W))
        val monDOpcode = Output(UInt(64.W))
        val monDParam = Output(UInt(64.W))
        val monDSize = Output(UInt(64.W))
        val monDSource = Output(UInt(64.W))
        val monDSink = Output(UInt(64.W))
        val monDDenied = Output(UInt(64.W))
        val monDData = Output(UInt(64.W))
        val monDCorrupt = Output(UInt(64.W))
        val monEValid = Output(UInt(64.W))
        val monEReady = Output(UInt(64.W))
        val monESink = Output(UInt(64.W))
        val posted = new PostedStoreCachePort(c)
        val flushRequest = Input(Bool())
        val flushDone = Output(Bool())
        val hit = Output(Bool())
        val miss = Output(Bool())
        val prefetchBusy = Output(Bool())
        val accepted = Output(Valid(new PostedStoreAcceptance(c)))
        val acknowledged = Output(Valid(new PostedStoreMember(c)))
        val acquired = Output(Valid(new PostedLineEvent(c)))
        val refillValid = Output(Bool())
        val refillEvent = Output(new PostedLineEvent(c))
        val refillError = Output(Bool())
        val installedValid = Output(Bool())
        val installedEvent = Output(new PostedLineEvent(c))
        val drained = Output(Valid(new PostedStoreMember(c)))
        val released = Output(Valid(new PostedLineEvent(c)))
        val attached = Output(Valid(new PostedWritebackEvent(c)))
        val sent = Output(Valid(new PostedWritebackEvent(c)))
        val completed = Output(Valid(new PostedWritebackEvent(c)))
        val cancelled = Output(Valid(new PostedLineEvent(c)))
        val fallback = Output(Valid(new PostedFallbackAcknowledgement(c)))
        val fallbackAck = Output(Valid(new PostedFallbackAcknowledgement(c)))
        val failed = Output(Bool())
        val mshrMask = Output(UInt(2.W))
        val postedMask = Output(UInt(2.W))
        val responseMask = Output(UInt(2.W))
        val responseCompleteMask = Output(UInt(2.W))
        val wbMask = Output(UInt(wbEntries.W))
        val lineWrite = Output(Bool())
        val lineWritePosted = Output(Bool())
        val lineWriteAddress = Output(UInt(64.W))
        val refillWord0 = Output(UInt(64.W)); val refillWord1 = Output(UInt(64.W))
        val refillWord2 = Output(UInt(64.W)); val refillWord3 = Output(UInt(64.W))
        val refillWord4 = Output(UInt(64.W)); val refillWord5 = Output(UInt(64.W))
        val refillWord6 = Output(UInt(64.W)); val refillWord7 = Output(UInt(64.W))
        val installWord0 = Output(UInt(64.W)); val installWord1 = Output(UInt(64.W))
        val installWord2 = Output(UInt(64.W)); val installWord3 = Output(UInt(64.W))
        val installWord4 = Output(UInt(64.W)); val installWord5 = Output(UInt(64.W))
        val installWord6 = Output(UInt(64.W)); val installWord7 = Output(UInt(64.W))
    })
    val cache = Module(new FullLineNonBlockingCoherentLineCache(base = c.guaranteedBase, bytes = c.guaranteedBytes, lines = 512,
        params = params, ways = 2, concurrency = concurrency,
        tagConfig = CacheTagConfig(compact = true, bankedStorage = true),
        postedConfig = Some(c), returnConfig = Some(returns),
        registerProbeLookup = true, localReadSelection = true, shareStoreWriteData = true,
        fullLineAllocation = enabled, collectionCycles = collectionCycles, compactMembers = compactMembers))
    io.upstream <> cache.io.upstream
    val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val home = Module(new FullLineMixedCoherentLineHome(params, base = c.guaranteedBase, bytes = c.guaranteedBytes,
        trackedLines = 512, trackedWays = 2, acquireEntries = 2,
        tagConfig = CacheTagConfig(compact = true, bankedStorage = true),
        rawResponseMetadata = true, writebackEntries = wbEntries, mixedReadWrite = true, distinctWayRelease = false,
        memoryScheduleOverlap = true, futureWayReservation = true,
        internalLineGrant = true, lineReadChannel = true, lineTransferDispatchFlow = true,
        sharedLookupMatch = true, dmaLineTransfers = true, dmaLineEntries = 4,
        permissionOnlyAllocation = enabled))
    val atomic = Module(new AtomicDataMemory(c.guaranteedBase, c.guaranteedBytes, registerResponseOwners = true,
        dmaLineTransfers = true, dmaLineEntries = 4))
    val requests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 4),
        axiAddressWidth = 32, axiIdWidth = 4, maxOutstanding = 4, maxBurstBeats = 16,
        maxOutstandingWrites = (if (wbEntries > 1) wbEntries else 0),
        unorderedResponses = true, lineReadChannel = true, writeCollectionFlow = true,
        localPayloadWriteEnable = true, localPayloadWriteRow = true, localAddressRanges = true,
        axiAddressBase = c.guaranteedBase, axiWindowBytes = c.guaranteedBytes))
    atomic.io.cpu <> cache.io.downstream
    atomic.io.dma <> io.dma
    atomic.io.dmaLine.get <> io.dmaLine
    home.io.dmaLine.get <> atomic.io.memoryLine.get
    atomic.io.clearReservation := false.B
    requests.io.upstream <> atomic.io.memory
    requests.io.requestCpu := atomic.io.memoryRequestCpu
    home.io.upstream <> requests.io.downstream
    home.io.upstreamRequestCpu := requests.io.downstreamRequestCpu
    home.io.clients(0) <> cache.io.tl
    home.io.clients(0).a.valid := cache.io.tl.a.valid && !io.holdAcquire
    cache.io.tl.a.ready := home.io.clients(0).a.ready && !io.holdAcquire
    home.io.clients(0).c.valid := cache.io.tl.c.valid && !io.holdCoherentC
    cache.io.tl.c.ready := home.io.clients(0).c.ready && !io.holdCoherentC
    home.io.clients(0).e.valid := cache.io.tl.e.valid && !io.holdGrantAck
    cache.io.tl.e.ready := home.io.clients(0).e.ready && !io.holdGrantAck
    // A test-only transport queue retains real home-produced ReleaseAck messages.
    // No fake source, permission, data or completion is synthesized here.
    val delayedAcks = Module(new Queue(chiselTypeOf(home.io.clients(0).d.bits), 4))
    val homeD = home.io.clients(0).d
    val incomingAck = homeD.bits.opcode === TLOpcode.ReleaseAck
    val captureAck = incomingAck && (io.holdReleaseAck || delayedAcks.io.deq.valid)
    val replayAck = delayedAcks.io.deq.valid && !io.holdReleaseAck && (!homeD.valid || incomingAck)
    delayedAcks.io.enq.valid := homeD.valid && captureAck
    delayedAcks.io.enq.bits := homeD.bits
    delayedAcks.io.deq.ready := replayAck && cache.io.tl.d.ready
    cache.io.tl.d.valid := replayAck || (homeD.valid && !captureAck)
    cache.io.tl.d.bits := Mux(replayAck, delayedAcks.io.deq.bits, homeD.bits)
    homeD.ready := Mux(captureAck, delayedAcks.io.enq.ready, !replayAck && cache.io.tl.d.ready)
    ordered.io.data <> home.io.downstream
    arbiter.io.masters(0) <> ordered.io.tl
    CoherentHomeUlBoundary.connect(home.io.line, arbiter.io.masters(1))
    ddr.io.tl <> arbiter.io.manager
    ddr.io.lineRead.get <> home.io.lineRead.get
    cache.io.lineGrant.get <> home.io.lineGrants.get(0)
    io.lineGrantValid := home.io.lineGrants.get(0).valid
    io.lineGrantReady := home.io.lineGrants.get(0).ready
    io.lineGrantBits := home.io.lineGrants.get(0).bits
    io.logicalRead := home.io.lineRead.get.request.fire
    io.logicalReadAddress := home.io.lineRead.get.request.bits.address
    io.decision := BoringUtils.bore(cache.observationFullLineDecision.get)
    io.ddrAxi <> ddr.io.axi
    home.io.drainRequest := io.flushRequest && cache.io.flushDone
    io.cacheFlushDone := cache.io.flushDone
    io.homeDrainDone := home.io.drainDone
    io.monAValid := cache.io.tl.a.valid
    io.monAReady := cache.io.tl.a.ready
    io.monAOpcode := cache.io.tl.a.bits.opcode
    io.monAParam := cache.io.tl.a.bits.param
    io.monASize := cache.io.tl.a.bits.size
    io.monASource := cache.io.tl.a.bits.source
    io.monAAddress := cache.io.tl.a.bits.address
    io.monAMask := cache.io.tl.a.bits.mask
    io.monAData := cache.io.tl.a.bits.data
    io.monACorrupt := cache.io.tl.a.bits.corrupt
    io.monBValid := cache.io.tl.b.valid
    io.monBReady := cache.io.tl.b.ready
    io.monBOpcode := cache.io.tl.b.bits.opcode
    io.monBParam := cache.io.tl.b.bits.param
    io.monBSize := cache.io.tl.b.bits.size
    io.monBSource := cache.io.tl.b.bits.source
    io.monBAddress := cache.io.tl.b.bits.address
    io.monBMask := cache.io.tl.b.bits.mask
    io.monBData := cache.io.tl.b.bits.data
    io.monBCorrupt := cache.io.tl.b.bits.corrupt
    io.monCValid := cache.io.tl.c.valid
    io.monCReady := cache.io.tl.c.ready
    io.monCOpcode := cache.io.tl.c.bits.opcode
    io.monCParam := cache.io.tl.c.bits.param
    io.monCSize := cache.io.tl.c.bits.size
    io.monCSource := cache.io.tl.c.bits.source
    io.monCAddress := cache.io.tl.c.bits.address
    io.monCData := cache.io.tl.c.bits.data
    io.monCCorrupt := cache.io.tl.c.bits.corrupt
    io.monDValid := cache.io.tl.d.valid
    io.monDReady := cache.io.tl.d.ready
    io.monDOpcode := cache.io.tl.d.bits.opcode
    io.monDParam := cache.io.tl.d.bits.param
    io.monDSize := cache.io.tl.d.bits.size
    io.monDSource := cache.io.tl.d.bits.source
    io.monDSink := cache.io.tl.d.bits.sink
    io.monDDenied := cache.io.tl.d.bits.denied
    io.monDData := cache.io.tl.d.bits.data
    io.monDCorrupt := cache.io.tl.d.bits.corrupt
    io.monEValid := cache.io.tl.e.valid
    io.monEReady := cache.io.tl.e.ready
    io.monESink := cache.io.tl.e.bits.sink
    cache.io.flushRequest := io.flushRequest
    io.flushDone := cache.io.flushDone && home.io.drainDone
    io.hit := cache.io.hit
    io.miss := cache.io.miss
    io.prefetchBusy := cache.io.prefetchBusy
    io.posted <> cache.io.posted.get
    val observation = BoringUtils.bore(cache.observationPosted.get)
    val line = BoringUtils.bore(cache.observationLineWrite)
    io.accepted := observation.accepted
    io.acknowledged := observation.acknowledged
    io.acquired := observation.acquired
    io.refillValid := observation.refillValid
    io.refillEvent := observation.refillEvent
    io.refillError := observation.refillError
    io.installedValid := observation.installed.valid
    io.installedEvent.context := observation.installed.bits.context
    io.installedEvent.reservation := observation.installed.bits.reservation
    io.drained := observation.drained
    io.released := observation.released
    io.attached := observation.attached
    io.sent := observation.sent
    io.completed := observation.completed
    io.cancelled := observation.cancelled
    io.fallback := observation.fallback
    io.fallbackAck := observation.fallbackAck
    io.failed := observation.failed
    io.mshrMask := observation.mshrMask
    io.postedMask := observation.postedMask
    io.responseMask := observation.responseMask
    io.responseCompleteMask := observation.responseCompleteMask
    io.wbMask := observation.wbMask
    io.lineWrite := line.valid
    io.lineWritePosted := line.posted
    io.lineWriteAddress := line.address
    Seq(io.refillWord0, io.refillWord1, io.refillWord2, io.refillWord3,
        io.refillWord4, io.refillWord5, io.refillWord6, io.refillWord7).zipWithIndex.foreach {
        case (port, i) => port := observation.refillData(64 * i + 63, 64 * i)
    }
    Seq(io.installWord0, io.installWord1, io.installWord2, io.installWord3,
        io.installWord4, io.installWord5, io.installWord6, io.installWord7).zipWithIndex.foreach {
        case (port, i) => port := line.data(64 * i + 63, 64 * i)
    }
}

object FullLineCacheGsimMain extends App {
    require(args.length == 5 && Set("0", "1").contains(args(1)) && Set("0", "1").contains(args(4)))
    var actual: FullLineCacheGsim = null
    ChiselStage.emitCHIRRTLFile({
        actual = new FullLineCacheGsim(args(1) == "1", args(2).toInt, args(3).toInt, compactMembers = args(4) == "1")
        actual
    }, Array("--target-dir", args.head))
    def obj(m: Map[String, String]): ujson.Obj = ujson.Obj.from(m.toSeq.sortBy(_._1).map {
        case (k,v) => k -> ujson.Str(v)
    })
    def product(p: Product): ujson.Obj = obj(p.productElementNames.zip(p.productIterator.map(_.toString)).toMap)
    val d = actual.ddr
    val observed = ujson.Obj(
        "cache" -> obj(actual.cache.experimentConfiguration),
        "home" -> obj(actual.home.experimentConfiguration),
        "concurrency" -> product(actual.concurrency),
        "posted" -> product(actual.c),
        "returns" -> product(actual.returns),
        "ddr" -> obj(Map(
            "axiAddressBase" -> d.axiAddressBase.toString, "axiWindowBytes" -> d.axiWindowBytes.toString,
            "axiAddressWidth" -> d.axiAddressWidth.toString, "axiIdWidth" -> d.axiIdWidth.toString,
            "maxBurstBeats" -> d.maxBurstBeats.toString, "maxOutstanding" -> d.maxOutstanding.toString,
            "maxOutstandingWrites" -> d.maxOutstandingWrites.toString, "unorderedResponses" -> d.unorderedResponses.toString,
            "writeCollectionFlow" -> d.writeCollectionFlow.toString, "lineReadChannel" -> d.lineReadChannel.toString,
            "localPayloadWriteEnable" -> d.localPayloadWriteEnable.toString,
            "localPayloadWriteRow" -> d.localPayloadWriteRow.toString, "localAddressRanges" -> d.localAddressRanges.toString)))
    java.nio.file.Files.writeString(java.nio.file.Paths.get(args.head, "ACTUAL_CONFIGURATION.json"),
        ujson.write(observed, indent = 2) + "\n")
}
