package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RankLegalityTimingSpec extends AnyFunSuite {
    test("rank-legality inherits the exact two-issue baseline with three opt-in flags") {
        val b = BoardSocConfig.timingParams("staged-decode-align")
        val p = BoardSocConfig.timingParams("staged-rank-legality")
        assert(p == b.copy(parallelBitLegality = true, parallelRenameRanks = true, parallelMinMaxWordResults = true))
        assert(p.renameWidth == 2 && p.physicalRegs == 48 && p.robEntries == 16)
        assert(!OooParams().parallelBitLegality && !OooParams().parallelRenameRanks &&
            !OooParams().parallelMinMaxWordResults)
    }
    test("legality and early W minmax are stateless without added latency") {
        for (rtl <- Seq(ChiselStage.emitCHIRRTL(new ParallelBitLegality),
            ChiselStage.emitCHIRRTL(new ParallelMinMaxResult),
            ChiselStage.emitCHIRRTL(new IntegerAlu(true, true, true, true)))) {
            assert(!rtl.contains("reg ") && !rtl.contains("regreset "))
        }
    }
    test("all candidate widths prepare free ranks independently without storage") {
        for ((width, registers) <- Seq((2, 48), (4, 64), (6, 96))) {
            val rtl = ChiselStage.emitCHIRRTL(new RenameDestinationCandidates(width, registers, true))
            assert(!rtl.contains("reg ") && !rtl.contains("regreset "))
        }
    }
}
