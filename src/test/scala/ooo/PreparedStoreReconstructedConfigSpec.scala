package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{FpgaNextConfig, OooParams}

/** New reconstruction checks. No historical qualification is inherited. */
class PreparedStoreReconstructedConfigSpec extends AnyFunSuite {
    test("default profiles leave reconstructed store preparation off") {
        assert(!OooParams().preparedStoreLookahead)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.preparedStoreLookahead && !base.coreParams.preparedStoreLookahead)
        }
    }
    test("explicit preparation changes no capacity or other core parameter") {
        for (entries <- Seq(2, 4)) {
            val off = FpgaNextConfig.fromOptions(Set("--selected", s"--lsu-entries=$entries"), false)
            val on = FpgaNextConfig.fromOptions(
                Set("--selected", s"--lsu-entries=$entries", "--prepared-store-lookahead"), false)
            assert(on == off.copy(preparedStoreLookahead = true))
            assert(on.coreParams.copy(preparedStoreLookahead = false) == off.coreParams)
            assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage)
            assert(on.issueWidth == 2 && !on.virtualRamLoadPrecheck && !on.precheckedDataRequestFlow)
        }
    }
    test("unstaged configurations reject lookahead") {
        intercept[IllegalArgumentException] { OooParams(preparedStoreLookahead = true) }
        val selected = FpgaNextConfig.Selected.coreParams
        intercept[IllegalArgumentException] {
            selected.copy(preparedStoreLookahead = true, parallelMemoryPreparation = false)
        }
        intercept[IllegalArgumentException] {
            selected.copy(preparedStoreLookahead = true, registeredMemoryAddress = false)
        }
    }
}
