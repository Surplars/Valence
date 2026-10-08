package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class SharedFetchPmpSpec extends AnyFunSuite {
    test("shared fetch relations are opt-in and preserve the selected core geometry") {
        val p = BoardSocConfig.boardParams("staged-fetch-turnover", isa = "rv64gc")
        assert(!p.sharedFetchPmpRelations)
        assert(p.copy(sharedFetchPmpRelations = true).copy(sharedFetchPmpRelations = false) == p)
        intercept[IllegalArgumentException] { OooParams(sharedFetchPmpRelations = true) }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new PacketFetchPmp(16, 2, sharedRelations = true))
        }
    }
    test("shared word comparisons elaborate without state for 1/2/4 instruction lanes") {
        for (width <- Seq(1, 2, 4); selected <- Seq(false, true)) {
            val fir = ChiselStage.emitCHIRRTL(new PacketFetchPmp(16, width,
                wordSpan = true, balancedComparisons = true, sharedRelations = selected))
            assert(!fir.contains("reg ") && !fir.contains("regreset ") && !fir.contains("smem ") && !fir.contains("cmem "))
            assert(fir.contains("UInt<64>"))
        }
    }
    test("shared word comparisons retain supported entry counts and reject unbounded windows") {
        for (entries <- Seq(0, 8, 16)) {
            val fir = ChiselStage.emitCHIRRTL(new PacketFetchPmp(entries, 2,
                wordSpan = true, sharedRelations = true))
            assert(!fir.contains("reg ") && !fir.contains("regreset ") && !fir.contains("mem "))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new PacketFetchPmp(16, 256, wordSpan = true, sharedRelations = true))
        }
    }
}
