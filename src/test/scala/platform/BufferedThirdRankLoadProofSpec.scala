package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class BufferedThirdRankLoadProofSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmpSplitTag
    private val candidate = CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof

    test("buffered third-rank preparation is a default-off single-flag descendant of the qualified split-tag control") {
        assert(!OooParams().bufferedThirdRankLoadProof && !FpgaNextConfig.Selected.bufferedThirdRankLoadProof)
        assert(!CommonCpuProfile.A1.fpga.bufferedThirdRankLoadProof)
        val c = candidate.config
        assert(c == control.config.copy(bufferedThirdRankLoadProof = true))
        assert(c.coreParams == control.config.coreParams.copy(bufferedThirdRankLoadProof = true))
        assert(c.copy(bufferedThirdRankLoadProof = false) == control.config)
        assert(c.cache == control.config.cache && c.ddr == control.config.ddr)
        assert(candidate.name != control.name && c.name != control.config.name)
        assert(CommonA1RebuildProfile.named(
            "full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag-buffered-third-rank") == candidate)
        for (profile <- CommonA1RebuildProfile.all) {
            assert(profile.config.bufferedThirdRankLoadProof == (Set[CommonA1RebuildProfile](candidate, CommonA1RebuildProfile.FullR1M3BufferedReturnFlow,
                CommonA1RebuildProfile.FullR1M3OrderedOwnerReady,
                    CommonA1RebuildProfile.FullR1M3AdvisoryOwner,
                    CommonA1RebuildProfile.FullR1M3CertifiedIngress,
                    CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon,
                    CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                    CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                    CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5).contains(profile)))
            assert(profile.config.coreParams.bufferedThirdRankLoadProof == (Set[CommonA1RebuildProfile](candidate, CommonA1RebuildProfile.FullR1M3BufferedReturnFlow,
                CommonA1RebuildProfile.FullR1M3OrderedOwnerReady,
                    CommonA1RebuildProfile.FullR1M3AdvisoryOwner,
                    CommonA1RebuildProfile.FullR1M3CertifiedIngress,
                    CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon,
                    CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                    CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                    CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5).contains(profile)))
        }
        val p = c.coreParams
        assert(p.elasticLoadProofSupply && p.guardedNaturalDataPmp && p.splitLowTagAdvance)
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.storeBufferEntries == 2)
        assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2 && p.tagBits == 64)
        assert(p.dataReturnHandleBits == 0 && c.cache.readMshrs == 2 && c.cache.responseEntries == 2)
        intercept[IllegalArgumentException] { c.managedBoard() }
    }

    test("buffered advisory rows require a distinct explicit memory policy rather than broadening the old contract") {
        assert(candidate.memoryProfile.contains(CommonA1MemoryProfile.ExperimentalBufferedThirdRankProof))
        assert(candidate.memoryProfile != control.memoryProfile)
        val policy = candidate.memoryProfile.get
        policy.validate(candidate.config, CommonCpuTilePortParams())
        policy.validate(candidate.config, CommonCpuTilePortParams(runtimeMaintenance = true,
            runtimeCancellation = true, runtimeInterruptHold = true))
        for (profile <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            intercept[IllegalArgumentException] { policy.validate(profile.config, CommonCpuTilePortParams()) }
            profile.memoryProfile.foreach { oldPolicy =>
                intercept[IllegalArgumentException] { oldPolicy.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        // The backend-only split-tag descendant still shares its original policy with guarded-natural PMP.
        assert(control.memoryProfile ==
            CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmp.memoryProfile)
    }

    test("source lifetime and geometry guards reject unsupported speculative readiness or storage topologies") {
        val p = candidate.config.coreParams
        val unsupported: Seq[() => OooParams] = Seq(
            () => p.copy(guardedNaturalDataPmp = false),
            () => p.copy(splitLowTagAdvance = false),
            () => p.copy(robEntries = 8),
            () => p.copy(physicalRegs = 64),
            () => p.copy(memoryEntries = 2),
            () => p.copy(lvtPhysicalRegisterFile = false),
            () => p.copy(bankedIssuePayload = false),
            () => p.copy(parallelPrfReadyUpdates = false),
            () => p.copy(ownerLocalIssueReady = false),
            () => p.copy(compactMemoryOperandSelect = false),
            () => p.copy(parallelMemoryPayload = false),
            () => p.copy(registeredIssueHeadMask = false),
            () => p.copy(moveAlias = true),
            () => p.copy(loadCompletionBypass = true),
            () => p.copy(mulWordPreviewBypass = true),
            () => p.copy(registeredLoadResultReady = true),
            () => p.copy(fastHeadLoadRetire = true))
        for (change <- unsupported) { intercept[IllegalArgumentException] { change() } }
        intercept[IllegalArgumentException] { OooParams(bufferedThirdRankLoadProof = true) }
        intercept[IllegalArgumentException] { candidate.config.copy(guardedNaturalDataPmp = false) }
        intercept[IllegalArgumentException] { candidate.config.copy(splitLowTagAdvance = false) }
        intercept[IllegalArgumentException] { candidate.config.copy(registeredLoadResultReady = true) }
    }
}
