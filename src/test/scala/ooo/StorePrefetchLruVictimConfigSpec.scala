package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Constructor/CLI isolation only; actual replacement and writeback tests use GSIM. */
class StorePrefetchLruVictimConfigSpec extends AnyFunSuite {
    test("victim policy is independent default off and rejects missing store origin") {
        assert(!CoherentCacheConcurrency().storePrefetchLruVictim)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.storePrefetchLruVictim && !base.cache.storePrefetchLruVictim)
        }
        intercept[IllegalArgumentException] {
            CoherentCacheConcurrency(2, nextLinePrefetch = true, storePrefetchLruVictim = true)
        }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--selected", "--store-prefetch-lru-victim"), true)
        }
        val noMru = CoherentCacheConcurrency(2, nextLinePrefetch = true,
            storeNextLinePrefetch = true, storePrefetchLruVictim = true)
        assert(noMru.storePrefetchLruVictim && !noMru.storePrefetchMruInsertion)
    }

    test("target pair differs only in the explicit cache policy and profile name") {
        val off = StorePrefetchLruVictimProfiles.profile(false)
        val on = StorePrefetchLruVictimProfiles.profile(true)
        assert(on.copy(storePrefetchLruVictim = false) == off)
        assert(on.cache.copy(storePrefetchLruVictim = false) == off.cache)
        assert(on.coreParams == off.coreParams && on.coreParams.memoryProofFrontier)
        val suffix = "-store-prefetch-lru-victim"
        assert(on.name.sliding(suffix.length).count(_ == suffix) == 1)
        assert(on.name.replace(suffix, "") == off.name)
        assert(StorePrefetchLruVictimProfiles.options(true) - "--store-prefetch-lru-victim" ==
            StorePrefetchLruVictimProfiles.options(false))
    }
}
