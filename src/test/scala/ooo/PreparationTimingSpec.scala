package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class PreparationTimingSpec extends AnyFunSuite {
    test("preparation candidate preserves two-issue capacities and existing pipeline boundaries") {
        val p = BoardSocConfig.timingParams("staged-preparation")
        assert(p == BoardSocConfig.timingParams("staged-redirect").copy(
            parallelMemoryPreparation = true, alignedFetchPmp = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(BoardSocConfig.timingProfile == "early-issue")
        assert(!BoardSocConfig.params.parallelMemoryPreparation && !BoardSocConfig.params.alignedFetchPmp)
        intercept[IllegalArgumentException] { OooParams(parallelMemoryPreparation = true) }
        intercept[IllegalArgumentException] { p.copy(loadCompletionBypass = true) }
        intercept[IllegalArgumentException] { p.copy(mulWordPreviewBypass = true) }
        intercept[IllegalArgumentException] { p.copy(fastBufferedStoreRetire = true) }
        intercept[IllegalArgumentException] { OooParams(alignedFetchPmp = true) }
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-preparation", 4) }
    }
    test("preparation planner has no state at compact and larger ROB capacities") {
        for (entries <- Seq(2, 16, 32)) {
            val rtl = ChiselStage.emitCHIRRTL(new MemoryPreparationSelector(OooParams(robEntries = entries)))
            assert(rtl.contains("module MemoryPreparationSelector"))
            assert(!rtl.linesIterator.exists(_.trim.startsWith("reg ")))
        }
    }
    test("aligned word PMP removes address-end addition without changing range width") {
        val rtl = ChiselStage.emitCHIRRTL(new PmpChecker(16, alignedWordAccess = true))
        assert(!rtl.contains("add("))
        assert(rtl.contains("UInt<65>"))
        val fetch = ChiselStage.emitCHIRRTL(new SynchronousFetch(16, compressed = true,
            cacheSets = 8, alignedFetchPmp = true))
        assert(fetch.contains("aligned word PMP checker requires"))
    }
}
