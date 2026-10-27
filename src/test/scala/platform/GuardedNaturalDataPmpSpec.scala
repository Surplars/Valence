package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class GuardedNaturalDataPmpSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProof
    private val candidate = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmp

    test("guarded natural main PMP is a default-off old-elastic candidate with unchanged capacities") {
        assert(!OooParams().guardedNaturalDataPmp && !FpgaNextConfig.Selected.guardedNaturalDataPmp)
        assert(!CommonCpuProfile.A1.fpga.guardedNaturalDataPmp)
        assert(candidate.config == control.config.copy(guardedNaturalDataPmp = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(guardedNaturalDataPmp = true))
        assert(candidate.config.translationHitFlow && candidate.config.combinedCheckedDataFlow)
        assert(!candidate.config.registeredDataTranslation && !candidate.config.factoredDataPmpRange)
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        candidate.memoryProfile.get.validate(candidate.config, CommonCpuTilePortParams())
        val splitTag = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmpSplitTag
        assert(splitTag.config.guardedNaturalDataPmp && splitTag.config.splitLowTagAdvance)
        assert(splitTag.memoryProfile == candidate.memoryProfile)
        candidate.memoryProfile.get.validate(splitTag.config, CommonCpuTilePortParams())
        splitTag.memoryProfile.get.validate(candidate.config, CommonCpuTilePortParams())
        val buffered = CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof
        assert(buffered.config.guardedNaturalDataPmp && buffered.config.bufferedThirdRankLoadProof)
        assert(buffered.memoryProfile != candidate.memoryProfile)
        intercept[IllegalArgumentException] {
            candidate.memoryProfile.get.validate(buffered.config, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] {
            buffered.memoryProfile.get.validate(candidate.config, CommonCpuTilePortParams())
        }
        for (old <- CommonA1RebuildProfile.all.filterNot(p => p == candidate || p == splitTag || p == buffered || p == CommonA1RebuildProfile.FullR1M3BufferedReturnFlow ||
            p == CommonA1RebuildProfile.FullR1M3OrderedOwnerReady ||
            p == CommonA1RebuildProfile.FullR1M3AdvisoryOwner ||
            p == CommonA1RebuildProfile.FullR1M3CertifiedIngress ||
            p == CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon ||
            p == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor ||
            p == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2 ||
            p == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3 ||
            p == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4)) {
            assert(!old.config.guardedNaturalDataPmp)
            old.memoryProfile.foreach { policy =>
                intercept[IllegalArgumentException] { policy.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] { candidate.memoryProfile.get.validate(control.config, CommonCpuTilePortParams()) }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
    }
    test("guarded natural main PMP cannot silently combine with other experimental authority routes") {
        val c = candidate.config
        intercept[IllegalArgumentException] { c.copy(registeredDataTranslation = true) }
        intercept[IllegalArgumentException] { c.copy(registeredRawCertifiedFlow = true) }
        intercept[IllegalArgumentException] { c.copy(factoredDataPmpRange = true) }
        intercept[IllegalArgumentException] { c.copy(physicalLoadIngressFlow = true) }
        intercept[IllegalArgumentException] { c.copy(frozenStoreProofTransport = true) }
        intercept[IllegalArgumentException] { c.copy(postedStoreMerge = true) }
        intercept[IllegalArgumentException] { c.copy(taggedStoreReturns = true) }
    }
    test("actual candidate uses existing natural checker without another register or factored range module") {
        def emit(profile: CommonA1RebuildProfile): String = ChiselStage.emitCHIRRTL(
            new DataTranslationAdapter(profile.config.coreParams, registerCheckedRequests = true,
                translationHitFlow = profile.config.translationHitFlow))
        val a = emit(control)
        val b = emit(candidate)
        assert(!a.contains("natural PMP checker requires an aligned access of at most eight bytes"))
        assert(b.contains("natural PMP checker requires an aligned access of at most eight bytes"))
        assert(!b.contains("PmpGenericRangeComparisons") && !b.contains("DataPhysicalPermissionEvaluator"))
    }
}
