package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class PublishedPmpChangesSpec extends AnyFunSuite {
    test("exact PMP change publication is explicit in all official parameter paths") {
        val base = FpgaNextConfig.Selected
        assert(!OooParams().publishedPmpChanges && !base.publishedPmpChanges)
        val options = Set("--selected", "--virtual-ram-load-precheck", "--published-pmp-changes")
        val profile = FpgaNextConfig.fromOptions(options, true)
        assert(profile.publishedPmpChanges && profile.coreParams.pmpChangePublicationEnabled)
        assert(profile.copy(publishedPmpChanges = false) == base.copy(virtualRamLoadPrecheck = true))
        assert(profile.coreParams.copy(publishedPmpChanges = false) ==
            base.copy(virtualRamLoadPrecheck = true).coreParams)
        assert(profile.cache == base.cache && profile.ddr == base.ddr)
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--published-pmp-changes=false"), true)
        }
    }
    test("unused publication has no state and standalone adapter fallback remains explicit") {
        for (entries <- Seq(0, 8, 16)) {
            val p = OooParams(machineSystem = true, pmpEntries = entries, publishedPmpChanges = true)
            assert(!p.pmpChangePublicationEnabled)
            val fir = ChiselStage.emitCHIRRTL(new MachineSystemUnit(p))
            assert(!fir.contains("pmpRawChanged") && !fir.contains("pmpRawChangeWrite"))
        }
        for (precheck <- Seq(false, true); posted <- Seq(false, true)) {
            val p = OooParams(machineSystem = true, pmpEntries = 8, virtualMemoryLevels = 3,
                publishedPmpChanges = true, virtualRamLoadPrecheck = precheck, postedStoreMerge = posted,
                bufferedRamStores = posted, registeredMemoryAddress = true, memoryEntries = 2,
                speculativeRamBase = BigInt("80000000", 16), speculativeRamBytes = 65536)
            assert(p.pmpChangePublicationEnabled == (precheck || posted))
            val fallback = ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p, registerCheckedRequests = true))
            assert(!fallback.contains("input pmpRawChanged"))
            assert(fallback.contains("previousPmp") == (precheck || posted))
            if (p.pmpChangePublicationEnabled) {
                val published = ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p,
                    registerCheckedRequests = true, usePublishedPmpChanges = true))
                assert(!published.contains("previousPmp"))
                assert(published.contains("previousVm") && published.contains("pmpRawChanged"))
            }
        }
    }
}
