package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class BufferedReturnFlowSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof
    private val candidate = CommonA1RebuildProfile.FullR1M3BufferedReturnFlow

    test("return flow and fixed-row identity form one explicit default-off descendant") {
        assert(!OooParams().bufferedReturnFlow && !FpgaNextConfig.Selected.bufferedReturnFlow)
        assert(!CommonCpuProfile.A1.fpga.bufferedReturnFlow)
        val c = candidate.config
        assert(c == control.config.copy(bufferedReturnFlow = true,
            translatedResponseEmptyFlow = true, reconstructIssueTokenIndex = true))
        assert(c.coreParams == control.config.coreParams.copy(bufferedReturnFlow = true,
            translatedResponseEmptyFlow = true, reconstructIssueTokenIndex = true))
        assert(c.cache == control.config.cache && c.ddr == control.config.ddr)
        assert(candidate.name == control.name + "-return-flow-index")
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        assert(candidate.config.name != control.config.name)
        val descendants = Set[CommonA1RebuildProfile](candidate,
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
            assert(profile.config.bufferedReturnFlow == descendants.contains(profile))
            assert(profile.config.coreParams.bufferedReturnFlow == descendants.contains(profile))
            assert(profile.config.translatedResponseEmptyFlow == descendants.contains(profile))
            assert(profile.config.reconstructIssueTokenIndex == descendants.contains(profile))
        }
        val p = c.coreParams
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.tagBits == 64)
        assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
        assert(p.storeBufferEntries == 2 && c.cache.readMshrs == 2 && c.cache.responseEntries == 2)
        assert(p.registeredMemoryRequests && p.registeredTranslationHeads && p.registeredTranslatedResponses)
        assert(p.registeredStoreResponseOwners && !p.registeredLocalStoreResponses)
        assert(!p.loadCompletionBypass && !p.registeredLoadResultReady && !p.fastHeadLoadRetire)
        assert(!p.fastBufferedStoreRetire && p.dataReturnHandleBits == 0)
        intercept[IllegalArgumentException] { c.managedBoard() }
    }

    test("new memory policy is exact and all previous policies still reject the experiment") {
        val policy = candidate.memoryProfile.get
        assert(policy == CommonA1MemoryProfile.ExperimentalBufferedReturnFlow)
        policy.validate(candidate.config, CommonCpuTilePortParams())
        policy.validate(candidate.config, CommonCpuTilePortParams(runtimeMaintenance = true,
            runtimeCancellation = true, runtimeInterruptHold = true))
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            intercept[IllegalArgumentException] { policy.validate(old.config, CommonCpuTilePortParams()) }
            old.memoryProfile.foreach { oldPolicy =>
                intercept[IllegalArgumentException] { oldPolicy.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        // Index-only is a separately bindable representation experiment, not the return-flow policy.
        val indexOnly = control.config.copy(reconstructIssueTokenIndex = true)
        assert(indexOnly.coreParams.reconstructIssueTokenIndex && !indexOnly.coreParams.bufferedReturnFlow)
        intercept[IllegalArgumentException] { policy.validate(indexOnly, CommonCpuTilePortParams()) }
        intercept[IllegalArgumentException] { control.config.copy(translatedResponseEmptyFlow = true) }
        intercept[IllegalArgumentException] { control.config.coreParams.copy(translatedResponseEmptyFlow = true) }
    }

    test("capability cannot remove a storage owner result boundary or enlarge the qualified geometry") {
        val p = candidate.config.coreParams
        val changes: Seq[() => OooParams] = Seq(
            () => p.copy(bufferedReturnFlow = false),
            () => p.copy(translatedResponseEmptyFlow = false),
            () => p.copy(reconstructIssueTokenIndex = false),
            () => p.copy(bufferedThirdRankLoadProof = false),
            () => p.copy(guardedNaturalDataPmp = false),
            () => p.copy(splitLowTagAdvance = false),
            () => p.copy(registeredMemoryRequests = false),
            () => p.copy(registeredTranslationHeads = false),
            () => p.copy(registeredTranslatedResponses = false),
            () => p.copy(registeredStoreResponseOwners = false),
            () => p.copy(registeredLocalStoreResponses = true),
            () => p.copy(loadCompletionBypass = true),
            () => p.copy(registeredLoadResultReady = true),
            () => p.copy(fastHeadLoadRetire = true),
            () => p.copy(fastBufferedStoreRetire = true),
            () => p.copy(taggedStoreReturns = true),
            () => p.copy(postedStoreMerge = true),
            () => p.copy(robEntries = 32),
            () => p.copy(memoryEntries = 8),
            () => p.copy(physicalRegs = 64),
            () => p.copy(tagBits = 32))
        for (change <- changes) { intercept[IllegalArgumentException] { change() } }
        intercept[IllegalArgumentException] { OooParams(bufferedReturnFlow = true) }
        val c = candidate.config
        intercept[IllegalArgumentException] { c.copy(bufferedReturnFlow = false) }
        intercept[IllegalArgumentException] { c.copy(translatedResponseEmptyFlow = false) }
        intercept[IllegalArgumentException] { c.copy(reconstructIssueTokenIndex = false) }
        intercept[IllegalArgumentException] { c.copy(bufferedThirdRankLoadProof = false) }
    }
}
