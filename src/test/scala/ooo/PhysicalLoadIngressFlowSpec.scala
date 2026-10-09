package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class PhysicalLoadIngressFlowSpec extends AnyFunSuite {
    test("physical ingress flow retains the selected CPU and cache geometry") {
        val baseline = FpgaNextConfig.Selected
        val candidate = baseline.copy(physicalLoadIngressFlow = true)
        assert(!OooParams().physicalLoadIngressFlow && !baseline.physicalLoadIngressFlow)
        assert(candidate.coreParams == baseline.coreParams.copy(physicalLoadIngressFlow = true))
        assert(candidate.coreParams.memoryEntries == 2 && candidate.issueWidth == 2)
        assert(candidate.cache == baseline.cache && candidate.ddr == baseline.ddr)
        assert(FpgaNextConfig.fromOptions(Set("--selected", "--physical-load-ingress-flow"),
            defaultSelected = false) == candidate)
    }

    test("physical ingress flow requires the registered LSU and checked identity boundaries") {
        val valid = FpgaNextConfig.Selected.copy(physicalLoadIngressFlow = true).coreParams
        intercept[IllegalArgumentException] { valid.copy(identityDataRequestFlow = false) }
        intercept[IllegalArgumentException] { valid.copy(registeredTranslationHeads = false) }
        intercept[IllegalArgumentException] { valid.copy(registeredMemoryRequests = false) }
    }
}
