package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class PayloadTimingSpec extends AnyFunSuite {
    test("payload candidate retains two-issue preparation cuts and default release") {
        val p = BoardSocConfig.timingParams("staged-payload")
        assert(p == BoardSocConfig.timingParams("staged-preparation").copy(
            parallelIssuePayload = true, rawFetchPresence = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(BoardSocConfig.timingProfile == "early-issue")
        assert(!BoardSocConfig.params.parallelIssuePayload && !BoardSocConfig.params.rawFetchPresence)
        intercept[IllegalArgumentException] { OooParams(parallelIssuePayload = true) }
        intercept[IllegalArgumentException] { p.copy(precompleteMispredictedBranch = false) }
        intercept[IllegalArgumentException] { OooParams(rawFetchPresence = true) }
        intercept[IllegalArgumentException] { p.copy(stableFetchFaultMetadata = false) }
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-payload", 4) }
    }
    test("circular issue selector has no registers or serial age comparisons") {
        for (entries <- Seq(2, 16, 32)) {
            val rtl = ChiselStage.emitCHIRRTL(new CircularIssueSelector(OooParams(robEntries = entries)))
            assert(rtl.contains("module CircularIssueSelector"))
            assert(!rtl.linesIterator.exists(_.trim.startsWith("reg ")))
            assert(!rtl.contains("sub("))
        }
    }
    test("raw fetch presence enforces the compressed stable-metadata contract") {
        for (width <- Seq(2, 4)) {
            val rtl = ChiselStage.emitCHIRRTL(new SynchronousFetch(16, compressed = true, cacheSets = 8,
                fetchWidth = width, stableFaultMetadata = true, alignedFetchPmp = true, rawFetchPresence = true))
            assert(rtl.contains("returningPayload"))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new SynchronousFetch(compressed = true, rawFetchPresence = true))
        }
    }
}
