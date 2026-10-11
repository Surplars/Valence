package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ReadPrefetchDirtyRetryConfigSpec extends AnyFunSuite {
    private val flag = "--read-prefetch-dirty-retry"
    private val prerequisites = Set("--store-next-line-prefetch", "--split-prefetch-tracking")

    test("read prefetch dirty retry is default OFF and changes only the selected cache policy") {
        assert(!CoherentCacheConcurrency().readPrefetchDirtyRetry)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.readPrefetchDirtyRetry && !base.cache.readPrefetchDirtyRetry)
            val off = base.copy(storeNextLinePrefetch = true, splitPrefetchTracking = true)
            val on = off.copy(readPrefetchDirtyRetry = true)
            assert(on.productArity == 56 && !on.pendingReadyStoreBypass && !on.boundHeadStoreOverlap && !on.pendingVirtualStoreProof && !on.frozenStoreProofTransport && on.pendingVirtualStoreProofSlots == 1 && !on.publishedPmpChanges && !on.registeredPmpRegions && !on.coreParams.registeredPmpRegions &&
                on.cache.productArity == 19)
            assert(on.copy(readPrefetchDirtyRetry = false) == off)
            assert(on.cache.copy(readPrefetchDirtyRetry = false) == off.cache)
            assert(on.coreParams == off.coreParams && on.ddr == off.ddr && on.tags == off.tags)
            assert(on.storage == off.storage && on.network == off.network &&
                on.floatingPointResources == off.floatingPointResources)
            assert(on.issueWidth == 2 && on.cacheWays == 2 && on.dataCacheLines == off.dataCacheLines &&
                on.instructionCacheLines == off.instructionCacheLines)
            assert(on.prefetchCandidateCycles == 1 && on.cache.prefetchCandidateCycles == 1)
            assert(on.name == off.name + "-read-prefetch-dirty-retry")
        }
    }

    test("dirty retry requires split tracking and preserves valid nonblocking owner capacities") {
        val off = CoherentCacheConcurrency(2, nextLinePrefetch = true, storeNextLinePrefetch = true,
            splitPrefetchTracking = true)
        val on = off.copy(readPrefetchDirtyRetry = true)
        assert(on.copy(readPrefetchDirtyRetry = false) == off)
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(readPrefetchDirtyRetry = true) }
        intercept[IllegalArgumentException] { on.copy(splitPrefetchTracking = false) }
        intercept[IllegalArgumentException] { on.copy(storeNextLinePrefetch = false) }
        intercept[IllegalArgumentException] { on.copy(nextLinePrefetch = false) }
        intercept[IllegalArgumentException] { on.copy(readMshrs = 1) }
        assert(on.copy(readMshrs = 4, responseEntries = 4).readPrefetchDirtyRetry)
        assert(on.copy(writebackEntries = 2, overlapWritebackRefill = true).readPrefetchDirtyRetry)
        intercept[IllegalArgumentException] { FpgaNextConfig(readPrefetchDirtyRetry = true) }
        intercept[IllegalArgumentException] {
            FpgaNextConfig(storeNextLinePrefetch = true, readPrefetchDirtyRetry = true)
        }
    }

    test("official options leave lifetime and other prefetch policies independent") {
        for (selector <- Seq("--reference", "--candidate", "--selected"); cycles <- Seq(1, 3, 16);
            insertion <- Seq(false, true); victim <- Seq(false, true); distinct <- Seq(false, true)) {
            val options = prerequisites ++ Set(selector, s"--prefetch-candidate-cycles=$cycles") ++
                (if (insertion) Set("--store-prefetch-mru-insertion") else Set.empty[String]) ++
                (if (victim) Set("--store-prefetch-lru-victim") else Set.empty[String]) ++
                (if (distinct) Set("--distinct-way-release") else Set.empty[String])
            val off = FpgaNextConfig.fromOptions(options, defaultSelected = false)
            val on = FpgaNextConfig.fromOptions(options + flag, defaultSelected = false)
            assert(on == off.copy(readPrefetchDirtyRetry = true))
            assert(on.cache == off.cache.copy(readPrefetchDirtyRetry = true))
            assert(on.cache.prefetchCandidateCycles == cycles && on.coreParams == off.coreParams)
            assert(on.name == off.name + "-read-prefetch-dirty-retry")
        }
    }

    test("missing prerequisites and valued boolean forms are rejected") {
        for (options <- Seq(Set(flag), Set(flag, "--store-next-line-prefetch"),
            Set(flag, "--split-prefetch-tracking"))) {
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(options, defaultSelected = true) }
        }
        for (value <- Seq("true", "false", "0", "1")) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(prerequisites + s"$flag=$value", defaultSelected = true)
            }
        }
    }
}
