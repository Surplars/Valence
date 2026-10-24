package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FetchOwnerContextSpec extends AnyFunSuite {
    test("optional physical context preserves the old interface and follows each buffer representation") {
        val old = ChiselStage.emitCHIRRTL(new InstructionRequestBuffer())
        assert(!old.contains("requestContext"))
        for ((flow, independent) <- Seq((false, false), (true, false), (true, true))) {
            val fir = ChiselStage.emitCHIRRTL(new InstructionRequestBuffer(2, flow, independent,
                withRequestContext = true))
            assert(fir.contains("requestContext") && fir.contains("privilege"))
        }
    }
    test("single and dual owner adapters actually export saved physical request context") {
        for (slots <- Seq(1, 2)) {
            val p = FpgaNextConfig.Selected.coreParams.copy(alignedFetchSinglePage = slots == 2)
            val fir = ChiselStage.emitCHIRRTL(new InstructionTranslationAdapter(p,
                transactionSlots = slots, withRequestContext = true))
            assert(fir.contains("requestContext"))
            assert(fir.contains(if (slots == 1) "module RegisteredInstructionTranslationEngine"
                else "module PipelinedAlignedFetchEngine"))
        }
    }
    test("owner-context cache refuses unowned prefetch rather than silently using live privilege") {
        val fir = ChiselStage.emitCHIRRTL(new InstructionLineCache(lines = 4, withRequestContext = true))
        assert(fir.contains("requestContext"))
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new InstructionLineCache(lines = 4,
                withRequestContext = true, prefetchEnabled = true))
        }
    }
}
