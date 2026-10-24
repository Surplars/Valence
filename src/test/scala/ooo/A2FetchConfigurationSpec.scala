package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class A2FetchConfigurationSpec extends AnyFunSuite {
    test("explicit aligned two-owner path really contains reservation, send and physical-return modules") {
        val p = FpgaNextConfig.Selected.coreParams.copy(alignedFetchSinglePage = true)
        val fir = ChiselStage.emitCHIRRTL(new InstructionTranslationAdapter(p, transactionSlots = 2))
        for (name <- Seq("PipelinedAlignedFetchEngine", "FetchCompletionLedger", "AlignedFetchPermissionStage",
            "OrderedFetchPhysicalReturns")) assert(fir.contains(s"module $name"))
        assert(!fir.contains("module RegisteredInstructionTranslationEngine"))
        val old = ChiselStage.emitCHIRRTL(new InstructionTranslationAdapter(p))
        assert(old.contains("module RegisteredInstructionTranslationEngine"))
        assert(!old.contains("module PipelinedAlignedFetchEngine"))
    }
    test("two owners reject unaligned translation and unimplemented prepared or key modes") {
        val p = FpgaNextConfig.Selected.coreParams.copy(alignedFetchSinglePage = false)
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new InstructionTranslationAdapter(p, transactionSlots = 2))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new InstructionTranslationAdapter(p, transactionSlots = 3))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new SynchronousFetch(16, compressed = true, cacheSets = 16,
                alignedFetchPmp = true, registeredWindow = true, boundedRequestFrontier = true,
                fetchAddressBeforePmp = true, transactionSlots = 2))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new SynchronousFetch(16, compressed = true, cacheSets = 16,
                alignedFetchPmp = true, parallelFetchTagLookup = true, registeredWindow = true,
                compactCacheKeys = true, transactionSlots = 2))
        }
    }
}
