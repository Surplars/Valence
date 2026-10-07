package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class SensitivePathsTimingSpec extends AnyFunSuite {
    test("sensitive paths batch keeps two-issue capacity and changes only three flags") {
        val p = BoardSocConfig.timingParams("staged-sensitive-paths")
        assert(p == BoardSocConfig.timingParams("staged-frontend-select").copy(
            parallelPredictionSources = true, parallelAddressSums = true, bufferedFetchRequests = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
        assert(!OooParams().parallelPredictionSources && !OooParams().parallelAddressSums &&
            !OooParams().bufferedFetchRequests && BoardSocConfig.timingProfile == "early-issue")
        intercept[IllegalArgumentException] { OooParams(parallelPredictionSources = true) }
        intercept[IllegalArgumentException] { OooParams(parallelAddressSums = true) }
    }
    test("prediction and arithmetic stay stateless with full64 arithmetic") {
        for (fir <- Seq(ChiselStage.emitCHIRRTL(new PredictionSourceQualification),
            ChiselStage.emitCHIRRTL(new IntegerAlu(true, true)))) {
            assert(!fir.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
        }
        val arithmetic = ChiselStage.emitCHIRRTL(new IntegerBitManip(true, true))
        assert(arithmetic.contains("left : UInt<64>") && arithmetic.contains("right : UInt<64>"))
    }
    test("instruction request buffer has occupancy-only ready and preserves word masks") {
        for (words <- Seq(2, 4)) {
            val fir = ChiselStage.emitCHIRRTL(new InstructionRequestBuffer(words))
            assert(fir.contains("Queue2_Request") && fir.contains(s"mask : UInt<$words>"))
            assert(fir.contains("responsePageFault") && fir.contains("responseError"))
        }
    }
}
