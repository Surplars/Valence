package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ReadPrefetchDemandAdoptionConfigSpec extends AnyFunSuite {
    private val flag = "--read-prefetch-demand-adoption"
    private val prerequisites = Set("--store-next-line-prefetch", "--split-prefetch-tracking",
        "--independent-demand-admission", "--virtual-ram-load-precheck", "--canonical-virtual-store-overlap")
    private val off = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2, writebackEntries = 2,
        overlapWritebackRefill = true, nextLinePrefetch = true, storeNextLinePrefetch = true,
        splitPrefetchTracking = true, independentDemandAdmission = true)
    test("adoption defaults OFF and changes only its policy") {
        assert(!CoherentCacheConcurrency().readPrefetchDemandAdoption)
        for (p <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected))
            assert(!p.readPrefetchDemandAdoption && !p.cache.readPrefetchDemandAdoption)
        val on = off.copy(readPrefetchDemandAdoption = true)
        assert(on.copy(readPrefetchDemandAdoption = false) == off)
        assert(on.productArity == 19 && on.readMshrs == 2 && on.responseEntries == 2 && on.writebackEntries == 2)
        assert(!on.readPrefetchDirtyRetry && !on.distinctWayRelease)
    }
    test("adoption requires existing independent split overlapping owners") {
        val on = off.copy(readPrefetchDemandAdoption = true)
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(readPrefetchDemandAdoption = true) }
        intercept[IllegalArgumentException] { on.copy(splitPrefetchTracking = false) }
        intercept[IllegalArgumentException] { on.copy(independentDemandAdmission = false) }
        intercept[IllegalArgumentException] { on.copy(readMshrs = 1) }
        intercept[IllegalArgumentException] { on.copy(writebackEntries = 1) }
        intercept[IllegalArgumentException] { on.copy(overlapWritebackRefill = false) }
        assert(on.copy(readMshrs = 4, responseEntries = 4, writebackEntries = 4).readPrefetchDemandAdoption)
        assert(on.copy(readPrefetchDirtyRetry = true, prefetchCandidateCycles = 16).readPrefetchDemandAdoption)
    }
    test("official flag preserves unrelated parameters and rejects valued booleans") {
        for (selector <- Seq("--reference", "--candidate", "--selected")) {
            val a = FpgaNextConfig.fromOptions(prerequisites + selector, defaultSelected = false)
            val b = FpgaNextConfig.fromOptions(prerequisites + selector + flag, defaultSelected = false)
            assert(b == a.copy(readPrefetchDemandAdoption = true))
            assert(b.cache == a.cache.copy(readPrefetchDemandAdoption = true))
            assert(b.coreParams == a.coreParams && b.ddr == a.ddr && b.tags == a.tags && b.issueWidth == 2)
        }
        for (value <- Seq("true", "false", "0", "1")) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(prerequisites + s"$flag=$value", defaultSelected = true)
            }
        }
        for (missing <- prerequisites) intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions((prerequisites - missing) + flag, defaultSelected = true)
        }
    }
}
