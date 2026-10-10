package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class TranslatedResponseFlowSpec extends AnyFunSuite {
    private val options = Set("--selected", "--lsu-entries=4", "--virtual-ram-load-precheck",
        "--physical-load-ingress-flow", "--load-order-older-retire", "--fetch-previous-packet",
        "--dma-line-transfers", "--dma-line-entries=4", "--data-translation-entries=16",
        "--prepared-store-lookahead", "--store-next-line-prefetch", "--store-prefetch-mru-insertion")

    test("response flow is independent, explicit and default off on the delivered profile") {
        val off = FpgaNextConfig.fromOptions(options, defaultSelected = true)
        val on = FpgaNextConfig.fromOptions(options + "--translated-response-empty-flow", defaultSelected = true)
        assert(!OooParams().translatedResponseEmptyFlow)
        assert(!FpgaNextConfig.Reference.translatedResponseEmptyFlow)
        assert(!FpgaNextConfig.Selected.translatedResponseEmptyFlow && !off.translatedResponseEmptyFlow)
        assert(on == off.copy(translatedResponseEmptyFlow = true))
        assert(on.coreParams == off.coreParams.copy(translatedResponseEmptyFlow = true))
        assert(on.coreParams.registeredTranslationHeads && on.coreParams.registeredTranslatedResponses)
        assert(on.coreParams.registeredFabricBoundary && on.coreParams.registeredMemoryRequests)
        assert(on.coreParams.virtualRamLoadPrecheck && !on.coreParams.precheckedDataRequestFlow)
        assert(on.coreParams.issueWidth == 2 && on.coreParams.memoryEntries == 4)
        assert(on.cache == off.cache && on.ddr == off.ddr && on.dataTranslationEntries == 16)
    }

    test("the local override cannot silently change unregistered request or response profiles") {
        intercept[IllegalArgumentException] { OooParams(translatedResponseEmptyFlow = true) }
        val on = FpgaNextConfig.fromOptions(options, true).coreParams.copy(translatedResponseEmptyFlow = true)
        intercept[IllegalArgumentException] { on.copy(registeredTranslationHeads = false) }
        intercept[IllegalArgumentException] { on.copy(registeredTranslatedResponses = false) }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new DataResponseBuffer(registerPayload = true, emptyFlow = true))
        }
    }

    test("off elaboration prunes the bypass and both modes retain the original two-register queue") {
        val off = ChiselStage.emitCHIRRTL(new TranslatedResponseFlowGsim(false))
        val on = ChiselStage.emitCHIRRTL(new TranslatedResponseFlowGsim(true))
        for (rtl <- Seq(off, on)) {
            assert(rtl.contains("module TwoEntryRegisterQueue"))
            assert(rtl.contains("reg head : { data : UInt<64>, error : UInt<1>, pageFault : UInt<1>}"))
            assert(rtl.contains("reg tail : { data : UInt<64>, error : UInt<1>, pageFault : UInt<1>}"))
        }
        assert(!off.contains("node empty ="))
        assert(on.contains("node empty ="))
    }
}
