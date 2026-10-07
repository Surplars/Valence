package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FrontendFeedbackTimingSpec extends AnyFunSuite {
    test("adjacent tag keys retain full64/context equality without adding a cycle") {
        // The five-entry registered window needs the additional offset 4.
        for (sets <- Seq(2, 8, 16, 64); offset <- 0 to 4) {
            val text = ChiselStage.emitCHIRRTL(new ParallelFetchTagLookup(sets, offset))
            assert(!text.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
            assert(text.contains("address : UInt<64>") && text.contains("context : UInt<3>"))
        }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new ParallelFetchTagLookup(8, -1)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new ParallelFetchTagLookup(8, 5)) }
    }

    test("compressed cache captures adjacent keys with original request ownership") {
        for (width <- Seq(2, 4); parallel <- Seq(false, true)) {
            val text = ChiselStage.emitCHIRRTL(new SynchronousFetch(compressed = true, cacheSets = 2,
                fetchWidth = width, stableFaultMetadata = true, rawFetchPresence = true,
                parallelFetchTagLookup = parallel))
            assert(text.contains("reg pendingBasePlusEight") && text.contains("reg pendingBaseMinus"))
            assert(text.contains("reg shiftedBases"))
            assert(text.contains("pendingStale") && text.contains("lockedStale") && text.contains("pendingContext"))
        }
    }

    test("raw successor hints store exact qualification alongside their original full tags") {
        for (compressed <- Seq(false, true)) {
            val text = ChiselStage.emitCHIRRTL(new RegisteredFetchPacket(2, compressed, BigInt("80000000", 16)))
            assert(text.contains("reg hintAligned") && text.contains("reg hintDifferent"))
            assert(text.contains("hintPc") && text.contains("hintInstruction") && text.contains("hintNextPc"))
            assert(text.contains("priorFault") && text.contains("expectedNext") && text.contains("invalidate"))
        }
    }
}
