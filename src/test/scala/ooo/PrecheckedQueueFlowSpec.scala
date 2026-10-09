package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class PrecheckedQueueFlowSpec extends AnyFunSuite {
    test("prechecked queue flow is an explicit default-off option with unchanged geometry") {
        assert(!OooParams().precheckedDataRequestFlow)
        assert(!FpgaNextConfig.Selected.precheckedDataRequestFlow)
        val base = FpgaNextConfig.Selected.copy(virtualRamLoadPrecheck = true)
        val candidate = base.copy(precheckedDataRequestFlow = true)
        assert(candidate.coreParams == base.coreParams.copy(precheckedDataRequestFlow = true))
        assert(candidate.coreParams.memoryEntries == 2 && candidate.issueWidth == 2)
        assert(candidate.cache == base.cache && candidate.ddr == base.ddr)
        assert(FpgaNextConfig.fromOptions(Set("--selected", "--virtual-ram-load-precheck",
            "--prechecked-data-flow"), defaultSelected = false) == candidate)
        intercept[IllegalArgumentException] {
            FpgaNextConfig.Selected.copy(precheckedDataRequestFlow = true)
        }
    }

    test("prechecked queue flow retains the registered permission boundaries") {
        val valid = VirtualLoadPrecheckFixture.params(true).copy(precheckedDataRequestFlow = true)
        intercept[IllegalArgumentException] { valid.copy(virtualRamLoadPrecheck = false) }
        intercept[IllegalArgumentException] { valid.copy(registeredTranslationHeads = false) }
    }
}
