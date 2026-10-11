package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class DistinctWayReleaseConfigSpec extends AnyFunSuite {
    test("distinct-way release is default OFF and preserves all other dimensions") {
        assert(!CoherentCacheConcurrency().distinctWayRelease)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.distinctWayRelease && !base.cache.distinctWayRelease)
            val off = base.copy(storeNextLinePrefetch = true)
            val on = off.copy(distinctWayRelease = true)
            assert(on.copy(distinctWayRelease = false) == off)
            assert(on.cache.copy(distinctWayRelease = false) == off.cache)
            assert(on.coreParams == off.coreParams && on.ddr == off.ddr && on.tags == off.tags)
            assert(on.name.replace("-distinct-way-release", "") == off.name)
        }
    }
    test("distinct-way release keeps both resource-reuse flags independent") {
        for (reconstruct <- Seq(false, true); shared <- Seq(false, true)) {
            val options = StorePrefetchLruVictimProfiles.options(true) ++ Set("--posted-preparation-priority") ++
                (if (reconstruct) Set("--reconstruct-issue-token-index") else Set.empty[String]) ++
                (if (shared) Set("--shared-memory-address-state") else Set.empty[String])
            val off = FpgaNextConfig.fromOptions(options, defaultSelected = false)
            val on = FpgaNextConfig.fromOptions(options + "--distinct-way-release", defaultSelected = false)
            assert(on.productArity == 35 && on.coreParams.productArity == 142 && on.cache.productArity == 12)
            assert(on == off.copy(distinctWayRelease = true))
            assert(on.cache == off.cache.copy(distinctWayRelease = true))
            assert(on.coreParams == off.coreParams && on.storage == off.storage)
            assert(on.reconstructIssueTokenIndex == reconstruct && on.sharedMemoryAddressState == shared)
            assert(on.coreParams.reconstructIssueTokenIndex == reconstruct &&
                on.coreParams.sharedMemoryAddressState == shared)
            assert(on.ddr == off.ddr && on.tags == off.tags && on.network == off.network &&
                on.floatingPointResources == off.floatingPointResources)
            assert(on.name.replace("-distinct-way-release", "") == off.name)
        }
    }
    test("the bounded original resources and actual checked-store PF are required") {
        val good = CoherentCacheConcurrency(readMshrs = 2, writebackEntries = 2,
            overlapWritebackRefill = true, nextLinePrefetch = true, storeNextLinePrefetch = true,
            distinctWayRelease = true)
        intercept[IllegalArgumentException] { good.copy(storeNextLinePrefetch = false) }
        intercept[IllegalArgumentException] { good.copy(overlapWritebackRefill = false) }
        intercept[IllegalArgumentException] { good.copy(writebackEntries = 4) }
        intercept[IllegalArgumentException] { good.copy(readMshrs = 4, responseEntries = 4) }
        intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set("--distinct-way-release"), true) }
        val selected = FpgaNextConfig.fromOptions(Set("--distinct-way-release", "--store-next-line-prefetch"), true)
        assert(selected.distinctWayRelease && selected.cache == good.copy(responseEntries = 2))
    }
}
