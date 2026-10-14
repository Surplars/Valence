package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo._

/** Actual private cache/engine/SRAM, synthetic external manager and authority premises.
  * This wrapper does not establish a real CPU proof or home-reachable schedule.
  */
class CacheWriteDataGsim(enabled: Boolean, share: Boolean, paired: Boolean,
    actualProfile: Boolean, wholeGrant: Boolean) extends Module {
    private val generationBits = 64
    private val wbEntries = 2
    private val registerProbeLookup = true
    private val localReadSelection = true
    require(!wholeGrant || actualProfile)
    // Exact saved board cache control profile, with geometry reduced to 16 lines.
    // OFF cannot enable postedPrefetchCoexistence because there is no posted owner.
    private val concurrency = if (actualProfile) CoherentCacheConcurrency(
        readMshrs = 2, responseEntries = 2, writebackEntries = 2,
        overlapWritebackRefill = true, nextLinePrefetch = true, prefetchCandidateCycles = 16,
        prefetchBreakOnStore = false, storeNextLinePrefetch = true, storePrefetchMruInsertion = true,
        postedPrefetchCoexistence = enabled, storePrefetchLruVictim = false, distinctWayRelease = false,
        independentDemandAdmission = true, splitPrefetchTracking = true, readPrefetchDirtyRetry = true,
        readPrefetchDemandAdoption = true, readPrefetchStoreHold = true, durableReadPrefetchCandidate = true,
        readPrefetchBehindStore = true, internalLineGrant = true, concurrentReadStorePrefetch = true,
        memoryScheduleOverlap = true, futureHomeWayReservation = false)
    else CoherentCacheConcurrency(2, 2, 2, overlapWritebackRefill = true,
        nextLinePrefetch = true, storeNextLinePrefetch = true)
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = concurrency.sourceBits,
        sinkBits = concurrency.sinkBits)
    private val c = PostedStoreMergeConfig(enabled = true, tokenTagBits = 64, tokenIndexBits = 4,
        generationBits = generationBits, cacheSets = 8, cacheWays = 2, writebackEntries = wbEntries,
        guaranteedBase = 4096, guaranteedBytes = 4096)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val tl = new TLBundle(params)
        val posted = new PostedStoreCachePort(c)
        val flushRequest = Input(Bool())
        val flushDone = Output(Bool())
        val readSelectionWbCapture = Output(Bool())
        val readSelectionWbDirect = Output(Bool())
        val readSelectionWbDirty = Output(Bool())
        val readSelectionQueuedWanted = Output(Bool())
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
    val cache = Module(new NonBlockingCoherentLineCache(base = 4096, bytes = 4096, lines = 16,
        params = params, ways = 2, concurrency = concurrency,
        tagConfig = CacheTagConfig(compact = true, bankedStorage = true),
        postedConfig = if (enabled) Some(c) else None, registerProbeLookup = registerProbeLookup,
        localReadSelection = localReadSelection, shareStoreWriteData = share))
    if (paired) CacheWriteDataPair.attach(cache, 4096, 4096, 16, params, 2,
        concurrency, CacheTagConfig(compact = true, bankedStorage = true),
        if (enabled) Some(c) else None, registerProbeLookup)
    io.upstream <> cache.io.upstream
    io.downstream <> cache.io.downstream
    io.tl.a <> cache.io.tl.a
    io.tl.b <> cache.io.tl.b
    io.tl.c <> cache.io.tl.c
    io.tl.e <> cache.io.tl.e
    if (wholeGrant) {
        // Synthetic external-manager transport adapter only. The real cache,
        // acquire engine and SRAM use their actual whole-Grant configuration.
        // The unchanged host offers eight independent software-memory words.
        val pending = RegInit(false.B)
        val beat = RegInit(0.U(3.W))
        val words = Reg(Vec(8, UInt(64.W)))
        val source = Reg(UInt(params.sourceBits.W))
        val sink = Reg(UInt(params.sinkBits.W))
        val cap = Reg(UInt(2.W))
        val denied = RegInit(false.B)
        val corrupt = RegInit(false.B)
        val collect = io.tl.d.bits.opcode === 5.U
        cache.io.tl.d.valid := io.tl.d.valid && !collect
        cache.io.tl.d.bits := io.tl.d.bits
        io.tl.d.ready := Mux(collect, !pending, cache.io.tl.d.ready)
        val grant = cache.io.lineGrant.get
        grant.valid := pending
        grant.bits.source := source
        grant.bits.sink := sink
        grant.bits.cap := cap
        grant.bits.denied := denied
        grant.bits.corrupt := corrupt
        grant.bits.data := words.asUInt
        when(grant.fire) { pending := false.B }
        when(io.tl.d.fire && collect) {
            assert(io.tl.d.bits.size === 6.U, "fixture Grant must be a full cache line")
            when(beat === 0.U) {
                source := io.tl.d.bits.source
                sink := io.tl.d.bits.sink
                cap := io.tl.d.bits.param
                denied := io.tl.d.bits.denied
                corrupt := io.tl.d.bits.corrupt
            }.otherwise {
                assert(io.tl.d.bits.source === source && io.tl.d.bits.sink === sink &&
                    io.tl.d.bits.param === cap, "fixture Grant burst changed owner")
                denied := denied || io.tl.d.bits.denied
                corrupt := corrupt || io.tl.d.bits.corrupt
            }
            words(beat) := io.tl.d.bits.data
            beat := beat + 1.U
            when(beat === 7.U) { pending := true.B }
        }
    } else {
        io.tl.d <> cache.io.tl.d
        cache.io.lineGrant.foreach { grant =>
            grant.valid := false.B
            grant.bits := 0.U.asTypeOf(grant.bits)
        }
    }
    cache.io.flushRequest := io.flushRequest
    io.flushDone := cache.io.flushDone
    io.hit := cache.io.hit
    io.miss := cache.io.miss
    io.prefetchBusy := cache.io.prefetchBusy
    if (enabled) io.posted <> cache.io.posted.get
    else { io.posted.busy := false.B; io.posted.episodeActive := false.B }
    val observation = if (enabled) BoringUtils.bore(cache.observationPosted.get)
        else 0.U.asTypeOf(new PostedStoreCacheObservation(c))
    val line = BoringUtils.bore(cache.observationLineWrite)
    val selection = BoringUtils.bore(cache.observationStorePrefetch)
    io.readSelectionWbCapture := selection.wbCapture
    io.readSelectionWbDirect := selection.wbCaptureDirect
    io.readSelectionWbDirty := selection.wbCaptureDirty
    io.readSelectionQueuedWanted := selection.queuedEvictWanted
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

object CacheWriteDataGsimMain extends App {
    require(args.length == 6 && args.drop(1).forall(x => Set("0", "1").contains(x)),
        "output postedEnabled shareStoreWriteData paired actualProfile wholeGrant")
    ChiselStage.emitCHIRRTLFile(new CacheWriteDataGsim(args(1) == "1", args(2) == "1",
        args(3) == "1", args(4) == "1", args(5) == "1"), Array("--target-dir", args.head))
}
