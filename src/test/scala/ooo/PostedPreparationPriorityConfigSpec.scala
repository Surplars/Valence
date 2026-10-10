package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{FpgaNextConfig, OooParams}

/** Configuration isolation only. Real scheduling/authorization qualification uses the separate GSIM fixture. */
class PostedPreparationPriorityConfigSpec extends AnyFunSuite {
    private val parents = Set("--prepared-store-lookahead", "--posted-store-merge")
    private val flag = "--posted-preparation-priority"

    test("all default profiles and the historical frontier/LRU contract keep priority off") {
        assert(!OooParams().postedPreparationPriority)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.postedPreparationPriority && !base.coreParams.postedPreparationPriority)
        }
        assert(!StorePrefetchLruVictimProfiles.profile(true).coreParams.postedPreparationPriority)
    }

    test("explicit native and board configuration changes exactly one core field") {
        for (selector <- Seq("--reference", "--candidate", "--selected"); entries <- Seq(2, 4)) {
            val flags = parents ++ Set(selector, s"--lsu-entries=$entries")
            val off = FpgaNextConfig.fromOptions(flags, defaultSelected = false)
            val on = FpgaNextConfig.fromOptions(flags + flag, defaultSelected = false)
            assert(on == off.copy(postedPreparationPriority = true))
            assert(on.coreParams.copy(postedPreparationPriority = false) == off.coreParams)
            assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage)
            assert(on.tags == off.tags && on.network == off.network && on.issueWidth == 2)
            assert(on.name.replace("-posted-preparation-priority", "") == off.name)
        }
    }

    test("the frontier and LRU combination admits only the independent explicit priority flag") {
        val off = StorePrefetchLruVictimProfiles.profile(true)
        val on = FpgaNextConfig.fromOptions(StorePrefetchLruVictimProfiles.options(true) + flag, false)
        assert(on == off.copy(postedPreparationPriority = true))
        assert(on.coreParams.copy(postedPreparationPriority = false) == off.coreParams)
        assert(on.cache == off.cache && on.coreParams.memoryProofFrontier && on.cache.storePrefetchLruVictim)
    }

    test("missing preparation or posted support fails at the public configuration boundary") {
        for (missing <- parents) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions((parents - missing) ++ Set("--selected", flag), false)
            }
        }
        intercept[IllegalArgumentException] { OooParams(postedPreparationPriority = true) }
        val on = FpgaNextConfig.fromOptions(parents ++ Set("--selected", flag), false).coreParams
        val rejected = Seq[() => OooParams](
            () => on.copy(preparedStoreLookahead = false),
            () => on.copy(postedStoreMerge = false),
            () => on.copy(registeredMemoryAddress = false),
            () => on.copy(parallelMemoryPreparation = false))
        rejected.foreach(make => intercept[IllegalArgumentException] { make() })
    }
}
