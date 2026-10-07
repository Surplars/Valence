package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FrontendSelectTimingSpec extends AnyFunSuite {
    test("frontend batch changes exactly three flags and keeps the two-issue release") {
        val p = BoardSocConfig.timingParams("staged-frontend-select")
        assert(p == BoardSocConfig.timingParams("staged-execute-select").copy(
            parallelFetchTagLookup = true, parallelFrontendControl = true, parallelAuipcQualification = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
        assert(!OooParams().parallelFetchTagLookup && !OooParams().parallelFrontendControl &&
            !OooParams().parallelAuipcQualification && BoardSocConfig.timingProfile == "early-issue")
        intercept[IllegalArgumentException] { OooParams(parallelFetchTagLookup = true) }
        intercept[IllegalArgumentException] { OooParams(parallelAuipcQualification = true) }
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-frontend-select", 4) }
    }
    test("frontend helpers add no storage/cycle and qualification has no full64 target input") {
        for (fir <- Seq(ChiselStage.emitCHIRRTL(new FrontendControlDecode),
            ChiselStage.emitCHIRRTL(new AuipcPredictionQualification))) {
            assert(!fir.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
            assert(!fir.contains("IntegerBitDecode") && !fir.contains("IntegerDecode"))
        }
        val guard = ChiselStage.emitCHIRRTL(new AuipcPredictionQualification)
        assert(guard.contains("upperImmediate : UInt<32>") && guard.contains("indirectImmediate : UInt<12>"))
        assert(!guard.contains("UInt<64>"))
    }
    test("parallel tags preserve full address/context and compressed fetch integration") {
        for (sets <- Seq(2, 8, 16, 64)) {
            val fir = ChiselStage.emitCHIRRTL(new ParallelFetchTagLookup(sets))
            assert(!fir.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
            assert(fir.contains("address : UInt<64>") && fir.contains("context : UInt<3>"))
        }
        val fetch = ChiselStage.emitCHIRRTL(new SynchronousFetch(compressed = true, cacheSets = 8,
            parallelFetchTagLookup = true))
        assert(fetch.contains("ParallelFetchTagLookup"))
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new SynchronousFetch(parallelFetchTagLookup = true))
        }
    }
}
