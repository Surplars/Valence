package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RedirectTimingSpec extends AnyFunSuite {
    test("redirect candidate retains retirement cuts and restores carry comparison") {
        val p = BoardSocConfig.timingParams("staged-redirect")
        assert(p == BoardSocConfig.timingParams("staged-retire").copy(
            balancedBranchCompare = false, earlyRedirectCapture = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(BoardSocConfig.timingProfile == "early-issue")
        assert(!BoardSocConfig.params.earlyRedirectCapture)
        intercept[IllegalArgumentException] { OooParams(earlyRedirectCapture = true) }
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-redirect", 4) }
    }
    test("capture planner is combinational and covers ascending and descending priorities") {
        for (width <- Seq(1, 2, 4, 6); descending <- Seq(false, true)) {
            val p = OooParams(completionWidth = width, registeredBranchRedirect = true)
            val rtl = ChiselStage.emitCHIRRTL(new EarlyRedirectCapture(p, descending))
            assert(rtl.contains("module EarlyRedirectCapture"))
            assert(!rtl.linesIterator.exists(_.trim.startsWith("reg ")))
        }
    }
}
