package ooo

import org.scalatest.funsuite.AnyFunSuite
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.core.ooo._

class StorePrefetchInsertionSpec extends AnyFunSuite {
    test("MRU is independent default off and requires checked store origin") {
        assert(!CoherentCacheConcurrency().storePrefetchMruInsertion)
        assert(!FpgaNextConfig().storePrefetchMruInsertion)
        intercept[IllegalArgumentException](CoherentCacheConcurrency(2, storePrefetchMruInsertion = true))
        intercept[IllegalArgumentException](CoherentCacheConcurrency(2, nextLinePrefetch = true, storePrefetchMruInsertion = true))
        intercept[IllegalArgumentException](FpgaNextConfig.fromOptions(Set("--selected", "--store-prefetch-mru-insertion"), true))
        val flags = Set("--selected", "--store-next-line-prefetch", "--data-translation-entries=16",
            "--virtual-ram-load-precheck", "--lsu-entries=4", "--prepared-store-lookahead")
        val off = FpgaNextConfig.fromOptions(flags, true)
        val on = FpgaNextConfig.fromOptions(flags + "--store-prefetch-mru-insertion", true)
        assert(on.copy(storePrefetchMruInsertion = false) == off)
        assert(on.cache.copy(storePrefetchMruInsertion = false) == off.cache)
        assert(on.coreParams == off.coreParams)
    }
    test("legal capacities stay independent; one-way insertion is a no-op") {
        var elaborated = 0
        var offElaborated = 0
        for (m <- Seq(1, 2, 4); w <- Seq(1, 2, 4) if m > 1 || w == 1) {
            val off = CoherentCacheConcurrency(m, math.max(2, m), w)
            assert(!off.storePrefetchMruInsertion)
            for (ways <- Seq(1, 2)) {
                val tl = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = off.sourceBits, sinkBits = off.sinkBits)
                val text = ChiselStage.emitCHIRRTL(if (m == 1)
                    new CoherentLineCache(BigInt("80010000", 16), 128 * 1024, 16, tl, ways,
                        off.responseEntries, CacheTagConfig.FullWidth)
                else new NonBlockingCoherentLineCache(BigInt("80010000", 16), 128 * 1024, 16,
                    tl, ways, off, CacheTagConfig.FullWidth))
                assert(text.contains("CoherentLineCache"))
                offElaborated += 1
            }
            if (m == 1) intercept[IllegalArgumentException](off.copy(nextLinePrefetch = true,
                storeNextLinePrefetch = true, storePrefetchMruInsertion = true))
            else for (ways <- Seq(1, 2); enabled <- Seq(false, true)) {
                val cfg = off.copy(nextLinePrefetch = true, storeNextLinePrefetch = true,
                    storePrefetchMruInsertion = enabled)
                val text = ChiselStage.emitCHIRRTL(new NonBlockingCoherentLineCache(
                    BigInt("80010000", 16), 128 * 1024, 16,
                    TLParams(addrWidth = 64, dataWidth = 64, sourceBits = cfg.sourceBits, sinkBits = cfg.sinkBits),
                    ways, cfg, CacheTagConfig.FullWidth))
                assert(text.contains("NonBlockingCoherentLineCache"))
                elaborated += 1
            }
        }
        assert(offElaborated == 14 && elaborated == 24)
    }
}
