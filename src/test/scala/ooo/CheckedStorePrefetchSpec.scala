package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams

class CheckedStorePrefetchSpec extends AnyFunSuite {
    test("store PF is separately default off and grows no owner capacity") {
        assert(!OooParams().dataStoreNextLinePrefetch)
        assert(!CoherentCacheConcurrency().storeNextLinePrefetch)
        val off = FpgaNextConfig.fromOptions(Set("--selected", "--virtual-ram-load-precheck", "--lsu-entries=4"), defaultSelected = true)
        val on = FpgaNextConfig.fromOptions(Set("--selected", "--virtual-ram-load-precheck", "--lsu-entries=4", "--store-next-line-prefetch"), defaultSelected = true)
        assert(!off.cache.storeNextLinePrefetch && !off.coreParams.dataStoreNextLinePrefetch)
        assert(on.cache.storeNextLinePrefetch && on.coreParams.dataStoreNextLinePrefetch)
        assert(on.copy(storeNextLinePrefetch = false) == off)
    }
    test("OFF and ON legal cache capacity boundaries elaborate") {
        for (m <- Seq(1, 2, 4); w <- Seq(1, 2, 4) if m > 1 || w == 1) {
            val cfg = CoherentCacheConcurrency(m, math.max(2, m), w)
            val tl = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = cfg.sourceBits, sinkBits = cfg.sinkBits)
            if (m == 1) ChiselStage.emitCHIRRTL(new CoherentLineCache(
                lines = 16, params = tl, responseEntries = cfg.responseEntries))
            else {
                ChiselStage.emitCHIRRTL(new NonBlockingCoherentLineCache(lines = 16, params = tl, concurrency = cfg))
                ChiselStage.emitCHIRRTL(new NonBlockingCoherentLineCache(lines = 16, params = tl,
                    concurrency = cfg.copy(nextLinePrefetch = true, storeNextLinePrefetch = true)))
            }
        }
    }
    test("valid capacities remain independent; unsupported store PF is rejected") {
        for (m <- Seq(1, 2, 4); w <- Seq(1, 2, 4) if m > 1 || w == 1) {
            val c = CoherentCacheConcurrency(m, math.max(2, m), w)
            assert(!c.storeNextLinePrefetch)
            if (m > 1) {
                val pf = c.copy(nextLinePrefetch = true, storeNextLinePrefetch = true)
                assert(pf.readMshrs == m && pf.writebackEntries == w)
            }
        }
        intercept[IllegalArgumentException](CoherentCacheConcurrency(2, storeNextLinePrefetch = true))
        intercept[IllegalArgumentException](CoherentCacheConcurrency(1, nextLinePrefetch = true, storeNextLinePrefetch = true))
        intercept[IllegalArgumentException](OooParams(dataStoreNextLinePrefetch = true))
    }
}
