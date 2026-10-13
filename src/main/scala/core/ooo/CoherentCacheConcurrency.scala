package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLParams}

/** Independent capacities: changing miss slots never changes cache geometry or LSU width. */
case class CoherentCacheConcurrency(readMshrs: Int = 1, responseEntries: Int = 2, writebackEntries: Int = 1,
    overlapWritebackRefill: Boolean = false, nextLinePrefetch: Boolean = false, prefetchCandidateCycles: Int = 1,
    prefetchBreakOnStore: Boolean = false, storeNextLinePrefetch: Boolean = false, storePrefetchMruInsertion: Boolean = false,
    postedPrefetchCoexistence: Boolean = false, storePrefetchLruVictim: Boolean = false,
    distinctWayRelease: Boolean = false, independentDemandAdmission: Boolean = false,
    splitPrefetchTracking: Boolean = false, readPrefetchDirtyRetry: Boolean = false,
    readPrefetchDemandAdoption: Boolean = false, readPrefetchStoreHold: Boolean = false,
    durableReadPrefetchCandidate: Boolean = false, readPrefetchBehindStore: Boolean = false,
    internalLineGrant: Boolean = false, concurrentReadStorePrefetch: Boolean = false,
    memoryScheduleOverlap: Boolean = false, futureHomeWayReservation: Boolean = false) {
    require(!futureHomeWayReservation || memoryScheduleOverlap,
        "future Home way reservation requires memory scheduling overlap")
    require(!memoryScheduleOverlap || (readMshrs == 2 && responseEntries == 2 && writebackEntries == 2 &&
        overlapWritebackRefill && independentDemandAdmission),
        "memory scheduling overlap preserves the reviewed two-owner independent cache")
    require(!internalLineGrant || (readMshrs == 2 && writebackEntries == 2 && overlapWritebackRefill),
        "whole Grant transport requires the reviewed bounded mixed Home/cache")
    require(!concurrentReadStorePrefetch || (readMshrs == 2 && writebackEntries == 2 &&
        independentDemandAdmission && durableReadPrefetchCandidate),
        "read/store PF coexistence requires existing two-MSHR/two-WB independent/durable owners")
    require(!independentDemandAdmission || readMshrs >= 2,
        "independent demand admission reuses the existing nonblocking miss owners")
    require(Set(1, 2, 4).contains(readMshrs))
    require(prefetchCandidateCycles >= 1 && prefetchCandidateCycles <= 32,
        "prefetch candidate lifetime must be in 1..32 allocation attempts")
    require(prefetchCandidateCycles == 1 || nextLinePrefetch,
        "retained prefetch candidates require next-line prefetch")
    require(!readPrefetchStoreHold || (nextLinePrefetch && prefetchCandidateCycles > 1),
        "read prefetch store hold requires next-line prefetch and an existing multi-cycle candidate")
    require(!durableReadPrefetchCandidate || (prefetchCandidateCycles == 16 && readMshrs == 2 &&
        writebackEntries == 2 && splitPrefetchTracking && readPrefetchDirtyRetry &&
        readPrefetchDemandAdoption && readPrefetchStoreHold),
        "durable read candidates require the reviewed 16-attempt two-MSHR/two-WB split retry/adoption/store-hold profile")
    require(!readPrefetchBehindStore || durableReadPrefetchCandidate,
        "read prefetch capture behind a store owner requires durable read candidates")
    require(!prefetchBreakOnStore || nextLinePrefetch,
        "store-sensitive prediction history requires next-line prefetch")
    require(!storeNextLinePrefetch || nextLinePrefetch,
        "checked store prediction requires next-line prefetch")
    require(!splitPrefetchTracking || (nextLinePrefetch && storeNextLinePrefetch),
        "split prefetch tracking requires next-line and checked store prefetch")
    require(!readPrefetchDemandAdoption || (splitPrefetchTracking && independentDemandAdmission &&
        readMshrs >= 2 && writebackEntries >= 2 && overlapWritebackRefill),
        "read prefetch demand adoption requires split tracking, independent admission and existing overlapping owners")
    require(!readPrefetchDirtyRetry || splitPrefetchTracking,
        "read prefetch dirty retry requires split read/store resident tracking")
    require(!storePrefetchMruInsertion || storeNextLinePrefetch,
        "store-origin MRU insertion requires checked store prefetch")
    require(!storePrefetchLruVictim || storeNextLinePrefetch,
        "store-origin LRU victim selection requires checked store prefetch")
    require(!distinctWayRelease || (readMshrs == 2 && writebackEntries == 2 &&
        overlapWritebackRefill && storeNextLinePrefetch),
        "distinct-way release requires the two-MSHR/two-WB checked-store-prefetch profile")
    require(!postedPrefetchCoexistence || (nextLinePrefetch && readMshrs == 2),
        "posted/prefetch coexistence requires the original two-MSHR prefetch cache")
    require(!nextLinePrefetch || readMshrs >= 2, "data prefetch reuses a second miss slot")
    require(responseEntries >= readMshrs && responseEntries >= 2 && responseEntries <= 16 &&
        (responseEntries & (responseEntries - 1)) == 0)
    require(Set(1, 2, 4).contains(writebackEntries))
    require(readMshrs > 1 || writebackEntries == 1, "legacy cache has one release owner")
    require(!overlapWritebackRefill || (readMshrs > 1 && writebackEntries >= 2))
    val acquireEntries: Int = math.max(2, readMshrs)
    val releaseSource: Int = acquireEntries
    val sourceBits: Int = log2Ceil(acquireEntries + writebackEntries)
    val sinkBits: Int = math.max(1, log2Ceil(readMshrs))
}

class DataPrefetchEvents extends Bundle {
    val candidate = Bool()
    val allocated = Bool()
    val useful = Bool()
    val error = Bool()
    val missOwners = UInt(3.W)
    val releaseOwners = UInt(3.W)
}

class CoherentLineCachePort(params: TLParams, postedConfig: Option[PostedStoreMergeConfig] = None,
    returnConfig: Option[CpuReturnConfig] = None, internalLineGrant: Boolean = false) extends Bundle {
    val posted = postedConfig.map(c => new PostedStoreCachePort(c))
    val upstream = Flipped(new DataPort(returnConfig.map(_.handleBits).getOrElse(0)))
    val downstream = new DataPort
    val tl = new TLBundle(params)
    val lineGrant = if (internalLineGrant) Some(Flipped(Decoupled(new soc.ip.tilelink.LineGrant(params)))) else None
    val flushRequest = Input(Bool())
    val flushDone = Output(Bool())
    val prefetchBusy = Output(Bool())
    val prefetch = Output(new DataPrefetchEvents)
    val hit = Output(Bool())
    val miss = Output(Bool())
    val profile = Output(new CoherentCacheProfile)
}

abstract class CoherentLineCacheModule(params: TLParams, postedConfig: Option[PostedStoreMergeConfig] = None,
    returnConfig: Option[CpuReturnConfig] = None, internalLineGrant: Boolean = false) extends Module {
    val io = IO(new CoherentLineCachePort(params, postedConfig, returnConfig, internalLineGrant))
    io.prefetch := 0.U.asTypeOf(new DataPrefetchEvents)
}

object CoherentLineCacheModule {
    /** Caller selects capacities explicitly; the reference implementation stays available unchanged. */
    def build(base: BigInt, bytes: BigInt, lines: Int, params: TLParams, ways: Int,
        concurrency: CoherentCacheConcurrency, tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
        postedConfig: Option[PostedStoreMergeConfig] = None,
        returnConfig: Option[CpuReturnConfig] = None, registerProbeLookup: Boolean = false): CoherentLineCacheModule = {
        require(!registerProbeLookup || concurrency.readMshrs > 1,
            "registered probe lookup requires the nonblocking cache constructor")
        require(returnConfig.isEmpty || (concurrency.readMshrs == 2 && concurrency.responseEntries == 2),
            "tagged CPU store returns retain the reviewed two-MSHR/two-response cache")
        require(!concurrency.postedPrefetchCoexistence || postedConfig.exists(_.enabled),
            "posted/prefetch coexistence requires an enabled posted owner")
        postedConfig.foreach(c => require(c.enabled && concurrency.readMshrs == 2,
            "posted integration requires explicit ON and original two-MSHR cache"))
        if (concurrency.readMshrs == 1) Module(new CoherentLineCache(base, bytes, lines, params, ways, concurrency.responseEntries, tagConfig))
        else Module(new NonBlockingCoherentLineCache(base, bytes, lines, params, ways, concurrency, tagConfig,
            postedConfig, returnConfig, registerProbeLookup))
    }
}
