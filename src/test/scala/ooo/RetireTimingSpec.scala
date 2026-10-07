package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RetireTimingSpec extends AnyFunSuite {
    test("retirement candidate inherits all rename cuts without adding cycles or capacity") {
        val p = BoardSocConfig.timingParams("staged-retire")
        assert(p == BoardSocConfig.timingParams("staged-rename").copy(balancedBranchCompare = true,
            separateBranchRetireFault = true, parallelReturnStackControl = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(BoardSocConfig.timingProfile == "early-issue")
        val rtl = ChiselStage.emitCHIRRTL(new BalancedBranchCompare)
        assert(!rtl.linesIterator.exists(_.trim.startsWith("reg ")))
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-retire", 4) }
    }
    test("fault fast path and two-lane RAS reject unsupported contracts") {
        intercept[IllegalArgumentException] { OooParams(separateBranchRetireFault = true) }
        intercept[IllegalArgumentException] {
            OooParams(registeredBranchRedirect = true, separateBranchRetireFault = true)
        }
        intercept[IllegalArgumentException] { OooParams(parallelReturnStackControl = true) }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new RetirementReturnStack(8, 4,
                pcDerivedLinks = true, parallelControl = true))
        }
        for (depth <- Seq(2, 8, 32)) {
            val rtl = ChiselStage.emitCHIRRTL(new RetirementReturnStack(depth, 2,
                pcDerivedLinks = true, parallelControl = true))
            assert(rtl.contains("module RetirementReturnStack"))
        }
    }
}
