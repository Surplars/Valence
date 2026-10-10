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
class PostedStoreCacheGsim(enabled: Boolean, generationBits: Int = 64, wbEntries: Int = 2) extends Module {
    private val concurrency = CoherentCacheConcurrency(2, 2, wbEntries,
        overlapWritebackRefill = wbEntries > 1, nextLinePrefetch = true, storeNextLinePrefetch = true)
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
        postedConfig = if (enabled) Some(c) else None))
    io.upstream <> cache.io.upstream
    io.downstream <> cache.io.downstream
    io.tl <> cache.io.tl
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

object PostedStoreCacheGsimMain extends App {
    require(args.length == 4 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new PostedStoreCacheGsim(args(1) == "1", args(2).toInt, args(3).toInt),
        Array("--target-dir", args.head))
}
