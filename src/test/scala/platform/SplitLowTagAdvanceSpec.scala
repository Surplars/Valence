package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class SplitLowTagAdvanceSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmp
    private val candidate = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmpSplitTag

    test("split-low tag advance is a default-off single-flag descendant of the qualified guarded control") {
        assert(!OooParams().splitLowTagAdvance && !FpgaNextConfig.Selected.splitLowTagAdvance)
        assert(!CommonCpuProfile.A1.fpga.splitLowTagAdvance)
        assert(candidate.config == control.config.copy(splitLowTagAdvance = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(splitLowTagAdvance = true))
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        assert(candidate.name != control.name && candidate.config.name != control.config.name)
        assert(CommonA1RebuildProfile.named(
            "full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag") == candidate)
        val descendants = Set[CommonA1RebuildProfile](candidate, CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof, CommonA1RebuildProfile.FullR1M3BufferedReturnFlow,
            CommonA1RebuildProfile.FullR1M3OrderedOwnerReady,
                CommonA1RebuildProfile.FullR1M3AdvisoryOwner,
                CommonA1RebuildProfile.FullR1M3CertifiedIngress,
                CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5,
                CommonA1RebuildProfile.FullR1M3MulLoadOperandCaptureExperiment,
                CommonA1RebuildProfile.FullR1M3ContextFetchPrefetchExperiment)
        for (profile <- CommonA1RebuildProfile.all) {
            assert(profile.config.splitLowTagAdvance == descendants.contains(profile))
            assert(profile.config.coreParams.splitLowTagAdvance == descendants.contains(profile))
        }
        val p = candidate.config.coreParams
        assert(p.tagBits == 64 && p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.storeBufferEntries == 2)
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
    }

    test("backend-only tag arithmetic retains the exact guarded memory policy in both directions") {
        assert(candidate.memoryProfile == control.memoryProfile)
        for (policy <- Seq(control.memoryProfile.get, candidate.memoryProfile.get);
             config <- Seq(control.config, candidate.config)) {
            policy.validate(config, CommonCpuTilePortParams())
            policy.validate(config, CommonCpuTilePortParams(runtimeMaintenance = true,
                runtimeCancellation = true, runtimeInterruptHold = true))
        }
        for (profile <- CommonA1RebuildProfile.all.filterNot(p => p == control || p == candidate);
             policy <- profile.memoryProfile) {
            intercept[IllegalArgumentException] { policy.validate(candidate.config, CommonCpuTilePortParams()) }
        }
    }

    test("unsupported ledger tag widths or rename widths cannot silently select the experiment") {
        val p = candidate.config.coreParams
        for (width <- Seq(1, 3, 4)) {
            intercept[IllegalArgumentException] { p.copy(renameWidth = width) }
        }
        for (bits <- Seq(2, 32, 63, 65)) {
            intercept[IllegalArgumentException] { p.copy(tagBits = bits) }
        }
        assert(OooParams(splitLowTagAdvance = true).splitLowTagAdvance)
    }
}
