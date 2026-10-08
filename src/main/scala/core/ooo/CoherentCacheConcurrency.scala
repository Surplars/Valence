package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLParams}

/** Independent capacities: changing miss slots never changes cache geometry or LSU width. */
case class CoherentCacheConcurrency(readMshrs: Int = 1, responseEntries: Int = 2, writebackEntries: Int = 1,
    overlapWritebackRefill: Boolean = false, nextLinePrefetch: Boolean = false) {
    require(Set(1, 2, 4).contains(readMshrs))
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

class CoherentLineCachePort(params: TLParams) extends Bundle {
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

abstract class CoherentLineCacheModule(params: TLParams) extends Module {
    val io = IO(new CoherentLineCachePort(params))
    io.prefetch := 0.U.asTypeOf(new DataPrefetchEvents)
}

object CoherentLineCacheModule {
    /** Caller selects capacities explicitly; the reference implementation stays available unchanged. */
    def build(base: BigInt, bytes: BigInt, lines: Int, params: TLParams, ways: Int,
        concurrency: CoherentCacheConcurrency, tagConfig: CacheTagConfig = CacheTagConfig.FullWidth): CoherentLineCacheModule = {
        if (concurrency.readMshrs == 1) Module(new CoherentLineCache(base, bytes, lines, params, ways, concurrency.responseEntries, tagConfig))
        else Module(new NonBlockingCoherentLineCache(base, bytes, lines, params, ways, concurrency, tagConfig))
    }
}
