package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class WordDestinationTimingSpec extends AnyFunSuite {
    test("word-destination preserves rank-legality with exactly two opt-in flags") {
        val baseline = BoardSocConfig.timingParams("staged-rank-legality")
        val candidate = BoardSocConfig.timingParams("staged-word-destination")
        assert(candidate == baseline.copy(parallelArchitecturalDestinations = true, parallelAluWordResults = true))
        assert(candidate.renameWidth == 2 && candidate.robEntries == 16 && candidate.physicalRegs == 48)
        assert(!OooParams().parallelArchitecturalDestinations && !OooParams().parallelAluWordResults)
    }
    test("early W and separated address payloads add no state or execute cycles") {
        val rtl = ChiselStage.emitCHIRRTL(new IntegerAlu(true, true, true, true, true))
        assert(!rtl.contains("reg ") && !rtl.contains("regreset "))
        assert(rtl.contains("addressResult"))
    }
    test("early payload flags reject incompatible parent configurations") {
        intercept[IllegalArgumentException](OooParams(parallelAluWordResults = true))
        intercept[IllegalArgumentException](OooParams(parallelArchitecturalDestinations = true))
    }
}
