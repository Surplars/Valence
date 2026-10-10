package ooo

import org.scalatest.funsuite.AnyFunSuite
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.core.ooo._

class PostedStoreCacheRebuildSpec extends AnyFunSuite {
    private val on = PostedStoreMergeConfig(enabled = true, tokenIndexBits = 4,
        cacheSets = 8, cacheWays = 2, guaranteedBase = 4096, guaranteedBytes = 4096)
    private def emit(m: Int, w: Int, posted: Option[PostedStoreMergeConfig]): String = {
        val cfg = CoherentCacheConcurrency(m, math.max(2, m), w, overlapWritebackRefill = w > 1)
        ChiselStage.emitCHIRRTL(new NonBlockingCoherentLineCache(base = 4096, bytes = 4096,
            lines = 16, ways = 2, params = TLParams(addrWidth = 64, sourceBits = cfg.sourceBits,
                sinkBits = cfg.sinkBits), concurrency = cfg,
            tagConfig = CacheTagConfig(compact = true, bankedStorage = true), postedConfig = posted))
    }
    test("OFF keeps original legal MSHR and WB geometries and removes posted state") {
        for (m <- Seq(2, 4); w <- Seq(1, 2, 4)) {
            val fir = emit(m, w, None)
            assert(!fir.contains("module PostedStoreMerge"))
            assert("""(?m)^\s*(reg|regreset)\s+(postedMshr|postedContext|postedReservation|responseKind|wbPosted|fallbackDrain)""".r.findFirstIn(fir).isEmpty)
            assert(fir.contains(s"regreset phase : UInt<3>[$m]"))
        }
        // Existing single-MSHR cache remains separately constructible.
        val legacy = ChiselStage.emitCHIRRTL(new CoherentLineCache(base = 4096, bytes = 4096, lines = 16,
            params = TLParams(addrWidth = 64, sourceBits = 3, sinkBits = 1), ways = 2))
        assert(!legacy.contains("module PostedStoreMerge"))
    }
    test("ON validates exact real physical resources and cache aperture") {
        intercept[IllegalArgumentException] { emit(2, 2, Some(on.copy(enabled = false))) }
        intercept[IllegalArgumentException] { emit(4, 2, Some(on)) }
        intercept[IllegalArgumentException] { emit(2, 1, Some(on)) }
        intercept[IllegalArgumentException] { emit(2, 2, Some(on.copy(cacheSets = 16))) }
        intercept[IllegalArgumentException] { emit(2, 2, Some(on.copy(guaranteedBytes = 8192))) }
    }
    test("posted integration retains one physical write site per original tag way and data bank") {
        val off = emit(2, 2, None)
        val enabled = emit(2, 2, Some(on))
        assert("write mport".r.findAllIn(off).length == 10)
        assert("write mport".r.findAllIn(enabled).length == 10)
        assert(enabled.contains("module PostedStoreMerge") && enabled.contains("issued"))
        assert(enabled.contains("regreset responseOwned : UInt<1>[2]"))
        assert(enabled.contains("regreset wbLive : UInt<1>[2]"))
        assert(enabled.contains("regreset phase : UInt<3>[2]"))
    }
}
