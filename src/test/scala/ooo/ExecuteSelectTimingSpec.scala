package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ExecuteSelectTimingSpec extends AnyFunSuite {
    test("execute selection batch retains exact recovery baseline and default release") {
        val p = BoardSocConfig.timingParams("staged-execute-select")
        assert(p == BoardSocConfig.timingParams("staged-recovery-control").copy(
            parallelIssueRanks = true, parallelAluResults = true, parallelCompletionPayload = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
        assert(!OooParams().parallelIssueRanks && !OooParams().parallelAluResults &&
            !OooParams().parallelCompletionPayload && BoardSocConfig.timingProfile == "early-issue")
        intercept[IllegalArgumentException] { OooParams(parallelIssueRanks = true) }
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-execute-select", 4) }
    }
    test("rank and result selection are stateless, with no added execution cycle") {
        for (n <- Seq(2, 4, 16, 32, 64)) {
            val fir = ChiselStage.emitCHIRRTL(new CircularIssueSelector(OooParams(robEntries = n), true))
            assert(!fir.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
            assert(!fir.contains("remaining =") && !fir.contains("sub("))
        }
        for (fir <- Seq(ChiselStage.emitCHIRRTL(new IntegerAlu(true)),
            ChiselStage.emitCHIRRTL(new ParallelCompletionPayload(OooParams())))) {
            assert(!fir.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
        }
    }
    test("completion qualification stays outside payload selection and preserves full64 ownership") {
        val fir = ChiselStage.emitCHIRRTL(new ParallelCompletionPayload(OooParams()))
        assert(fir.contains("tag : UInt<64>") && fir.contains("fallback :"))
        assert(!fir.contains("completionAccepted") && !fir.contains("recover"))
    }
}
