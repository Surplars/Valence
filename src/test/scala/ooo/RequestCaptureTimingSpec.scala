package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RequestCaptureTimingSpec extends AnyFunSuite {
    test("request-capture adds only two opt-in flags and preserves two-issue geometry") {
        val prior = BoardSocConfig.timingParams("staged-word-destination")
        val next = BoardSocConfig.timingParams("staged-request-capture")
        assert(next == prior.copy(independentFetchCapture = true, parallelHomeQualification = true))
        assert(next.renameWidth == 2 && next.robEntries == 16 && next.physicalRegs == 48)
        assert(!OooParams().independentFetchCapture && !OooParams().parallelHomeQualification)
        intercept[IllegalArgumentException](OooParams(independentFetchCapture = true))
    }
    test("both instruction widths retain an empty bypass and occupancy-only credit") {
        for (words <- Seq(2, 4)) {
            val fir = ChiselStage.emitCHIRRTL(new InstructionRequestBuffer(words, true, true))
            assert(fir.contains("storage") && fir.contains("maybeFull"))
            assert(!fir.contains("module Queue"))
        }
    }
    test("parallel way ownership and exact DDR qualification are stateless") {
        val fir = ChiselStage.emitCHIRRTL(new HomeQualificationGsim(BigInt("80200000", 16), BigInt(536870912)))
        assert(!fir.contains("reg ") && !fir.contains("regreset "))
        assert(fir.contains("ParallelHomeLineMatch"))
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new InstructionRequestBuffer(2, false, true))
        }
    }
}
