package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Pure constructor checks; directed CPU/cache ownership proof is a separate GSIM gate. */
class PostedPrefetchHeadOfferConfigSpec extends AnyFunSuite {
    private val flags = Set("--selected", "--posted-store-merge", "--posted-prefetch-coexistence",
        "--virtual-ram-load-precheck", "--data-translation-entries=16", "--prepared-store-lookahead",
        "--store-next-line-prefetch", "--store-prefetch-mru-insertion", "--lsu-entries=4",
        "--physical-load-ingress-flow", "--load-order-older-retire", "--fetch-previous-packet",
        "--dma-line-transfers", "--dma-line-entries=4")

    test("head offer is default off and changes only the explicit CPU policy") {
        assert(!OooParams().postedPrefetchHeadOffer)
        for (config <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!config.postedPrefetchHeadOffer && !config.coreParams.postedPrefetchHeadOffer)
        }
        val off = FpgaNextConfig.fromOptions(flags, defaultSelected = true)
        val on = FpgaNextConfig.fromOptions(flags + "--posted-prefetch-head-offer", defaultSelected = true)
        assert(!off.postedPrefetchHeadOffer && on.postedPrefetchHeadOffer)
        assert(on.copy(postedPrefetchHeadOffer = false) == off)
        assert(on.coreParams.postedPrefetchHeadOffer)
        assert(on.coreParams.copy(postedPrefetchHeadOffer = false) == off.coreParams)
        assert(on.cache == off.cache && on.ddr == off.ddr && on.network == off.network)
        assert(on.coreParams.postedProofConfig == off.coreParams.postedProofConfig)
        val suffix = "-posted-prefetch-head-offer"
        assert(on.name.sliding(suffix.length).count(_ == suffix) == 1)
        assert(on.name.replace(suffix, "") == off.name)
        assert(on.coreParams.registeredMemoryAddress && !on.coreParams.fastBufferedStoreRetire)
        // Store-origin PF is independent: an assembly with read PF alone remains legal.
        val readOnly = on.copy(storeNextLinePrefetch = false, storePrefetchMruInsertion = false)
        assert(readOnly.coreParams.postedPrefetchHeadOffer && readOnly.cache.nextLinePrefetch)
        assert(!readOnly.coreParams.dataStoreNextLinePrefetch)
    }

    test("head offer rejects missing authority, PF coexistence and incompatible retirement") {
        intercept[IllegalArgumentException] { OooParams(postedPrefetchHeadOffer = true) }
        for (missing <- Seq("--posted-store-merge", "--posted-prefetch-coexistence")) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions((flags - missing) + "--posted-prefetch-head-offer", true)
            }
        }
        val on = FpgaNextConfig.fromOptions(flags + "--posted-prefetch-head-offer", true)
        intercept[IllegalArgumentException] { on.coreParams.copy(postedStoreMerge = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(dataNextLinePrefetch = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(registeredMemoryAddress = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(fastBufferedStoreRetire = true) }
        intercept[IllegalArgumentException] { on.copy(postedPrefetchCoexistence = false) }
        intercept[IllegalArgumentException] { on.copy(precheckedDataRequestFlow = true) }
    }
}
