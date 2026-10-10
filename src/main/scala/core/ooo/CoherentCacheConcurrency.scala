package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLParams}

/** Independent capacities: changing miss slots never changes cache geometry or LSU width. */
case class CoherentCacheConcurrency(readMshrs: Int = 1, responseEntries: Int = 2, writebackEntries: Int = 1,
    overlapWritebackRefill: Boolean = false, nextLinePrefetch: Boolean = false, prefetchCandidateCycles: Int = 1, prefetchBreakOnStore: Boolean = false, storeNextLinePrefetch: Boolean = false, storePrefetchMruInsertion: Boolean = false) {
    require(Set(1, 2, 4).contains(readMshrs))
    require(prefetchCandidateCycles >= 1 && prefetchCandidateCycles <= 32,
        "prefetch candidate lifetime must be in 1..32 allocation attempts")
    require(prefetchCandidateCycles == 1 || nextLinePrefetch,
        "retained prefetch candidates require next-line prefetch")
    require(!prefetchBreakOnStore || nextLinePrefetch,
        "store-sensitive prediction history requires next-line prefetch")
    require(!storeNextLinePrefetch || nextLinePrefetch,
        "checked store prediction requires next-line prefetch")
    require(!storePrefetchMruInsertion || storeNextLinePrefetch,
        "store-origin MRU insertion requires checked store prefetch")
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

class CoherentLineCachePort(params: TLParams, postedConfig: Option[PostedStoreMergeConfig] = None) extends Bundle {
    val posted = postedConfig.map(c => new PostedStoreCachePort(c))
    val upstream = Flipped(new DataPort)
    val downstream = new DataPort
    val tl = new TLBundle(params)
    val flushRequest = Input(Bool())
    val flushDone = Output(Bool())
    val prefetchBusy = Output(Bool())
    val prefetch = Output(new DataPrefetchEvents)
    val hit = Output(Bool())
    val miss = Output(Bool())
    val profile = Output(new CoherentCacheProfile)
}

abstract class CoherentLineCacheModule(params: TLParams, postedConfig: Option[PostedStoreMergeConfig] = None) extends Module {
    val io = IO(new CoherentLineCachePort(params, postedConfig))
    io.prefetch := 0.U.asTypeOf(new DataPrefetchEvents)
}

object CoherentLineCacheModule {
    /** Caller selects capacities explicitly; the reference implementation stays available unchanged. */
    def build(base: BigInt, bytes: BigInt, lines: Int, params: TLParams, ways: Int,
        concurrency: CoherentCacheConcurrency, tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
        postedConfig: Option[PostedStoreMergeConfig] = None): CoherentLineCacheModule = {
        postedConfig.foreach(c => require(c.enabled && concurrency.readMshrs == 2,
            "posted integration requires explicit ON and original two-MSHR cache"))
        if (concurrency.readMshrs == 1) Module(new CoherentLineCache(base, bytes, lines, params, ways, concurrency.responseEntries, tagConfig))
        else Module(new NonBlockingCoherentLineCache(base, bytes, lines, params, ways, concurrency, tagConfig, postedConfig))
    }
}
