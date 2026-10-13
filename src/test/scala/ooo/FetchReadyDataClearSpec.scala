package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FetchReadyDataClearSpec extends AnyFunSuite {
    test("ready-only reply initialization is default-off and restricted to registered translation heads") {
        assert(!OooParams().fetchReadyDataClear)
        intercept[IllegalArgumentException] { OooParams(fetchReadyDataClear = true) }
        val baseline = BoardSocConfig.timingParams("staged-fetch-turnover")
        assert(!baseline.fetchReadyDataClear)
        val candidate = baseline.copy(fetchReadyDataClear = true)
        assert(candidate.copy(fetchReadyDataClear = false) == baseline)
        assert(candidate.registeredTranslationHeads && candidate.fetchReplyTurnover && candidate.issueWidth == 2)
    }
}
