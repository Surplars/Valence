package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class SplitPrefetchTrackingConfigSpec extends AnyFunSuite {
    private val flag = "--split-prefetch-tracking"

    test("split tracking is default OFF and changes only the selected cache policy") {
        assert(!CoherentCacheConcurrency().splitPrefetchTracking)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.splitPrefetchTracking && !base.cache.splitPrefetchTracking)
            val off = base.copy(storeNextLinePrefetch = true)
            val on = off.copy(splitPrefetchTracking = true)
            assert(on.productArity == 44 && on.cache.productArity == 14)
            assert(on.copy(splitPrefetchTracking = false) == off)
            assert(on.cache.copy(splitPrefetchTracking = false) == off.cache)
            assert(on.coreParams == off.coreParams && on.ddr == off.ddr && on.tags == off.tags)
            assert(on.storage == off.storage && on.network == off.network &&
                on.floatingPointResources == off.floatingPointResources)
            assert(on.issueWidth == 2 && on.cacheWays == off.cacheWays &&
                on.dataCacheLines == off.dataCacheLines && on.instructionCacheLines == off.instructionCacheLines)
            assert(on.prefetchCandidateCycles == 1 && on.cache.prefetchCandidateCycles == 1)
            assert(on.name == off.name + "-split-prefetch-tracking")
        }
    }

    test("split tracking requires both predictors without restricting valid nonblocking capacities") {
        val off = CoherentCacheConcurrency(2, nextLinePrefetch = true, storeNextLinePrefetch = true)
        val on = off.copy(splitPrefetchTracking = true)
        assert(on.copy(splitPrefetchTracking = false) == off)
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(splitPrefetchTracking = true) }
        intercept[IllegalArgumentException] { on.copy(storeNextLinePrefetch = false) }
        intercept[IllegalArgumentException] { on.copy(nextLinePrefetch = false) }
        intercept[IllegalArgumentException] { on.copy(readMshrs = 1) }
        assert(on.copy(readMshrs = 4, responseEntries = 4).splitPrefetchTracking)
        assert(on.copy(readMshrs = 4, responseEntries = 4, writebackEntries = 4,
            overlapWritebackRefill = true).splitPrefetchTracking)
        intercept[IllegalArgumentException] { FpgaNextConfig(splitPrefetchTracking = true) }
    }

    test("official options keep lifetime and other prefetch policies independent") {
        for (selector <- Seq("--reference", "--candidate", "--selected"); cycles <- Seq(1, 3, 16);
            insertion <- Seq(false, true); victim <- Seq(false, true); distinct <- Seq(false, true)) {
            val options = Set(selector, "--store-next-line-prefetch", s"--prefetch-candidate-cycles=$cycles") ++
                (if (insertion) Set("--store-prefetch-mru-insertion") else Set.empty[String]) ++
                (if (victim) Set("--store-prefetch-lru-victim") else Set.empty[String]) ++
                (if (distinct) Set("--distinct-way-release") else Set.empty[String])
            val off = FpgaNextConfig.fromOptions(options, defaultSelected = false)
            val on = FpgaNextConfig.fromOptions(options + flag, defaultSelected = false)
            assert(on == off.copy(splitPrefetchTracking = true))
            assert(on.cache == off.cache.copy(splitPrefetchTracking = true))
            assert(on.cache.prefetchCandidateCycles == cycles)
            assert(on.coreParams == off.coreParams)
            assert(on.name == off.name + "-split-prefetch-tracking")
        }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set(flag), defaultSelected = true)
        }
        for (value <- Seq("true", "false", "1")) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(Set("--store-next-line-prefetch", s"$flag=$value"),
                    defaultSelected = true)
            }
        }
    }
}
