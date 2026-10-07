package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ExecuteTimingSpec extends AnyFunSuite {
    test("execute candidate inherits data cuts without widening or changing grant latency") {
        val p = BoardSocConfig.timingParams("staged-execute")
        assert(p == BoardSocConfig.timingParams("staged-data").copy(
            earlyRankedOperands = true, pcDerivedReturnLinks = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48)
        assert(BoardSocConfig.timingProfile == "early-issue")
        assert(!BoardSocConfig.timingParams("staged-data").earlyRankedOperands)
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-execute", 4) }
    }
    test("operand evaluation cannot silently use an unsupported scheduler") {
        intercept[IllegalArgumentException] { OooParams(earlyRankedOperands = true) }
        intercept[IllegalArgumentException] {
            OooParams(registeredBranchRedirect = true, completionWidth = 4, earlyRankedOperands = true)
        }
        val rtl = ChiselStage.emitCHIRRTL(new ReturnStackGsim)
        assert(rtl.contains("module RetirementReturnStack"))
    }
    test("return stack port and capacity contracts elaborate independently of CPU") {
        for ((depth, width) <- Seq((2, 1), (8, 2), (16, 4), (32, 6))) {
            ChiselStage.emitCHIRRTL(new RetirementReturnStack(depth, width, pcDerivedLinks = true))
            ChiselStage.emitCHIRRTL(new RetirementReturnStack(depth, width, pcDerivedLinks = false))
        }
    }
}
