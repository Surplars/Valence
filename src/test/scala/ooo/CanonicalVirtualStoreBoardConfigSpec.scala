package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Public constructor/CLI contracts; actual graph correspondence is a separate elaboration gate. */
class CanonicalVirtualStoreBoardConfigSpec extends AnyFunSuite {
    private val flag = "--canonical-virtual-store-overlap"

    test("public option explicitly changes only canonical overlap and the profile name") {
        for (selector <- Seq("--reference", "--candidate", "--selected"); owners <- Seq(2, 4)) {
            val options = Set(selector, "--virtual-ram-load-precheck", s"--lsu-entries=$owners")
            val off = FpgaNextConfig.fromOptions(options, defaultSelected = false)
            val on = FpgaNextConfig.fromOptions(options + flag, defaultSelected = false)
            assert(on.canonicalVirtualStoreOverlap && on.coreParams.canonicalVirtualStoreOverlap)
            assert(!off.canonicalVirtualStoreOverlap && !off.coreParams.canonicalVirtualStoreOverlap)
            assert(on.copy(canonicalVirtualStoreOverlap = false) == off)
            assert(on.coreParams.copy(canonicalVirtualStoreOverlap = false) == off.coreParams)
            assert(on.name == off.name + "-canonical-virtual-store-overlap")
            assert(on.coreParams.memoryEntries == owners)
        }
    }

    test("public constructors reject a missing explicit load precheck") {
        val message = "canonical virtual store overlap requires explicit virtual RAM load precheck"
        for (options <- Seq(Set(flag), Set("--selected", flag), Set("--candidate", flag))) {
            val error = intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(options, defaultSelected = true)
            }
            assert(error.getMessage.contains(message))
        }
        intercept[IllegalArgumentException] { FpgaNextConfig(canonicalVirtualStoreOverlap = true) }
    }

    test("board transport preserves the full qualified parameter set") {
        val off = PostedPrefetchBoardProfiles.profile("head-offer", "on")
        val on = off.copy(canonicalVirtualStoreOverlap = true)
        val direct = BoardSocConfig.boardParams(on.timingProfile, on.issueWidth,
            externalDdr = true, isa = on.isaProfile, ddrMemoryBytes = on.ddrBytes,
            virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true)
        assert(direct.canonicalVirtualStoreOverlap && direct.virtualRamLoadPrecheck)
        assert(on.coreParams == off.coreParams.copy(canonicalVirtualStoreOverlap = true))
        assert(on.postedStoreMerge && on.postedPrefetchCoexistence && on.postedPrefetchHeadOffer)
        assert(!on.precheckedDataRequestFlow && !on.translatedResponseEmptyFlow)
        assert(on.productArity == 31 && on.coreParams.productArity == 139)
    }
}
