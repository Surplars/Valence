package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{FpgaNextConfig, OooParams}

class CombinedReconstructedProfileSpec extends AnyFunSuite {
    private val common = Set("--selected", "--lsu-entries=4", "--virtual-ram-load-precheck",
        "--physical-load-ingress-flow", "--load-order-older-retire", "--fetch-previous-packet",
        "--dma-line-transfers", "--dma-line-entries=4")
    test("new defaults keep both experiments off and D8") {
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(c.dataTranslationEntries == 8)
            assert(!c.preparedStoreLookahead && !c.storeNextLinePrefetch)
            assert(!c.coreParams.preparedStoreLookahead && !c.coreParams.dataStoreNextLinePrefetch)
        }
        assert(!OooParams().preparedStoreLookahead && !OooParams().dataStoreNextLinePrefetch)
    }
    test("A and B differ only in D capacity; C adds only the two explicit store options") {
        val a = FpgaNextConfig.fromOptions(common + "--data-translation-entries=8", false)
        val b = FpgaNextConfig.fromOptions(common + "--data-translation-entries=16", false)
        val c = FpgaNextConfig.fromOptions(common ++ Set("--data-translation-entries=16",
            "--prepared-store-lookahead", "--store-next-line-prefetch"), false)
        assert(b == a.copy(dataTranslationEntries = 16))
        assert(b.coreParams == a.coreParams && b.cache == a.cache)
        assert(c == b.copy(preparedStoreLookahead = true, storeNextLinePrefetch = true))
        assert(c.coreParams.copy(preparedStoreLookahead = false, dataStoreNextLinePrefetch = false) == b.coreParams)
        for (p <- Seq(a, b, c)) {
            assert(!p.prefetchBreakOnStore && p.prefetchCandidateCycles == 1)
            assert(!p.precheckedDataRequestFlow && p.virtualRamLoadPrecheck)
            assert(p.issueWidth == 2 && p.lsuEntries == 4 && p.dmaLineEntries == 4)
        }
    }
}
