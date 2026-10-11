package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.FpgaNextConfig

class TranslationHitFlowConfigSpec extends AnyFunSuite {
    test("default OFF preserves all core parameters, owners and geometry") {
        val base = FpgaNextConfig.Selected.copy(virtualRamLoadPrecheck = true)
        val on = base.copy(translationHitFlow = true)
        assert(base.productArity == 45 && !base.readPrefetchDirtyRetry && !base.cache.readPrefetchDirtyRetry &&
            !base.splitPrefetchTracking && !base.cache.splitPrefetchTracking &&
            !base.translationHitFlow)
        assert(on.coreParams == base.coreParams && on.cache == base.cache && on.ddr == base.ddr)
        assert(on.dataTranslationEntries == 8 && on.lsuEntries == 2 && on.dmaLineEntries == 1)
        assert(FpgaNextConfig.fromOptions(Set("--selected", "--virtual-ram-load-precheck",
            "--translation-hit-flow"), defaultSelected = false) == on)
    }
    test("reject missing stable precheck and ambiguous separate load-flow experiment") {
        intercept[IllegalArgumentException] { FpgaNextConfig.Selected.copy(translationHitFlow = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig.Selected.copy(virtualRamLoadPrecheck = true,
            precheckedDataRequestFlow = true, translationHitFlow = true) }
    }
}
