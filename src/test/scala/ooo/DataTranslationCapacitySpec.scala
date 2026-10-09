package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{FpgaNextConfig, SvTranslationService}

/** Pure configuration checks: no hardware simulation or elaboration. */
class DataTranslationCapacitySpec extends AnyFunSuite {
    private val selectedOptions = Set("--selected", "--dma-line-transfers", "--dma-line-entries=4",
        "--lsu-entries=4", "--physical-load-ingress-flow", "--load-order-older-retire",
        "--fetch-previous-packet", "--virtual-ram-load-precheck")

    test("D-TLB defaults remain eight in every profile") {
        assert(SvTranslationService.DefaultEntries == 8)
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(c.dataTranslationEntries == 8)
        }
        assert(FpgaNextConfig.fromOptions(selectedOptions, false).dataTranslationEntries == 8)
    }
    test("legal capacities have exact wrapping replacement widths") {
        assert(SvTranslationService.SupportedEntries == Set(4, 8, 16, 32))
        for ((entries, bits) <- Seq(4 -> 2, 8 -> 3, 16 -> 4, 32 -> 5)) {
            assert(SvTranslationService.indexBits(entries) == bits)
            assert((1 << bits) == entries)
            assert(((entries - 1 + 1) & ((1 << bits) - 1)) == 0)
        }
    }
    test("capacity changes only the D-side configuration and preserves selected core semantics") {
        val base = FpgaNextConfig.fromOptions(selectedOptions, false)
        for (entries <- Seq(4, 8, 16, 32)) {
            val changed = FpgaNextConfig.fromOptions(selectedOptions + s"--data-translation-entries=$entries", false)
            assert(changed == base.copy(dataTranslationEntries = entries))
            assert(changed.coreParams == base.coreParams)
            assert(changed.cache == base.cache && changed.ddr == base.ddr && changed.storage == base.storage)
            assert(!changed.precheckedDataRequestFlow)
            assert(changed.virtualRamLoadPrecheck && changed.issueWidth == 2)
        }
    }
    test("invalid and conflicting capacity requests are rejected") {
        for (entries <- Seq(Int.MinValue, -1, 0, 1, 2, 3, 6, 9, 15, 17, 31, 33, 64, Int.MaxValue)) {
            intercept[IllegalArgumentException] { SvTranslationService.indexBits(entries) }
            intercept[IllegalArgumentException] { FpgaNextConfig(dataTranslationEntries = entries) }
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(selectedOptions + s"--data-translation-entries=$entries", false)
            }
        }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(selectedOptions ++ Set("--data-translation-entries=8",
                "--data-translation-entries=16"), false)
        }
        intercept[NumberFormatException] {
            FpgaNextConfig.fromOptions(selectedOptions + "--data-translation-entries=nope", false)
        }
    }
}
