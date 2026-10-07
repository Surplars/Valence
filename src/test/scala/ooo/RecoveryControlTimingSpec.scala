package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RecoveryControlTimingSpec extends AnyFunSuite {
    test("recovery control inherits the exact two-issue fetch-control candidate") {
        val p = BoardSocConfig.timingParams("staged-recovery-control")
        assert(p == BoardSocConfig.timingParams("staged-fetch-control").copy(
            parallelRecoveryAdmission = true, parallelRedirectTokens = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
        assert(!OooParams().parallelRecoveryAdmission && !OooParams().parallelRedirectTokens)
        assert(BoardSocConfig.timingProfile == "early-issue")
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-recovery-control", 4) }
        intercept[IllegalArgumentException] { OooParams(parallelRedirectTokens = true) }
    }
    test("candidate checks and redirect matching are combinational with full tags") {
        for (entries <- Seq(4, 16, 32, 64); tags <- Seq(8, 64)) {
            val p = OooParams(robEntries = entries, tagBits = tags)
            for (fir <- Seq(ChiselStage.emitCHIRRTL(new ParallelRecoveryAdmission(p)),
                ChiselStage.emitCHIRRTL(new RedirectTokenQualification(p)))) {
                assert(!fir.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
                assert(fir.contains(s"tag : UInt<$tags>"))
            }
        }
    }
    test("ledger uses pre-admitted original candidates and per-slot completion retention") {
        val fir = ChiselStage.emitCHIRRTL(new RenameRob(BoardSocConfig.timingParams("staged-recovery-control")))
        assert(fir.contains("of ParallelRecoveryAdmission"))
        assert(fir.contains("recoveryAdmission.io.survives"))
        assert(!fir.contains("io.recover.bits.token.tag"))
    }
}
