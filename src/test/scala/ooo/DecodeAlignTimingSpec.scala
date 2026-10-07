package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class DecodeAlignTimingSpec extends AnyFunSuite {
    test("decode alignment batch changes four flags without widening or changing release") {
        val p = BoardSocConfig.timingParams("staged-decode-align")
        assert(p == BoardSocConfig.timingParams("staged-sensitive-paths").copy(
            parallelFetchAlignment = true, parallelDecodeLegality = true,
            flowThroughFetchRequests = true, parallelMinMaxResults = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48)
        val d = OooParams()
        assert(!d.parallelFetchAlignment && !d.parallelDecodeLegality &&
            !d.flowThroughFetchRequests && !d.parallelMinMaxResults)
        intercept[IllegalArgumentException] { OooParams(flowThroughFetchRequests = true) }
        intercept[IllegalArgumentException] { OooParams(parallelMinMaxResults = true) }
        intercept[IllegalArgumentException] { OooParams(parallelFetchAlignment = true) }
    }
    test("alignment legality and minmax add no register or execute cycle") {
        for (fir <- Seq(ChiselStage.emitCHIRRTL(new ParallelFetchAlignment(2)),
            ChiselStage.emitCHIRRTL(new ParallelFetchAlignment(4)),
            ChiselStage.emitCHIRRTL(new ParallelIntegerLegality(true, true)),
            ChiselStage.emitCHIRRTL(new IntegerAlu(true, true, true)))) {
            assert(!fir.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
        }
    }
    test("empty-flow instruction buffer retains two entries and full masks") {
        for (words <- Seq(2, 4)) {
            val fir = ChiselStage.emitCHIRRTL(new InstructionRequestBuffer(words, true))
            assert(fir.contains("Queue2_Request") && fir.contains(s"mask : UInt<$words>"))
        }
    }
}
