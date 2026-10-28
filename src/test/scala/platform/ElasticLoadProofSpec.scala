package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class ElasticLoadProofSpec extends AnyFunSuite {
    test("elastic proof supply has one explicit flag and a distinct memory policy without new credits") {
        val control = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRow.config
        val profile = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProof
        val candidate = profile.config
        assert(!OooParams().elasticLoadProofSupply && !FpgaNextConfig.Selected.elasticLoadProofSupply)
        assert(!CommonCpuProfile.A1.fpga.elasticLoadProofSupply)
        assert(candidate == control.copy(elasticLoadProofSupply = true))
        assert(candidate.coreParams == control.coreParams.copy(elasticLoadProofSupply = true))
        assert(candidate.cache == control.cache && candidate.ddr == control.ddr)
        assert(candidate.name != control.name)
        assert(candidate.coreParams.memoryEntries == 4 && candidate.cache.readMshrs == 2)
        assert(CommonA1RebuildProfile.named("full-r1-m3-checked-flow-store-row-elastic-proof") == profile)
        profile.memoryProfile.get.validate(candidate, CommonCpuTilePortParams())
        val registeredRaw = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofRegisteredRaw
        assert(registeredRaw.config.elasticLoadProofSupply)
        intercept[IllegalArgumentException] {
            profile.memoryProfile.get.validate(registeredRaw.config, CommonCpuTilePortParams())
        }
        val factored = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofFactoredPmp
        assert(factored.config.elasticLoadProofSupply)
        intercept[IllegalArgumentException] {
            profile.memoryProfile.get.validate(factored.config, CommonCpuTilePortParams())
        }
        val guarded = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmp
        assert(guarded.config.elasticLoadProofSupply)
        intercept[IllegalArgumentException] {
            profile.memoryProfile.get.validate(guarded.config, CommonCpuTilePortParams())
        }
        val splitTag = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmpSplitTag
        assert(splitTag.config.elasticLoadProofSupply && splitTag.config.splitLowTagAdvance)
        intercept[IllegalArgumentException] {
            profile.memoryProfile.get.validate(splitTag.config, CommonCpuTilePortParams())
        }
        val buffered = CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof
        assert(buffered.config.elasticLoadProofSupply && buffered.config.bufferedThirdRankLoadProof)
        intercept[IllegalArgumentException] {
            profile.memoryProfile.get.validate(buffered.config, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] {
            buffered.memoryProfile.get.validate(candidate, CommonCpuTilePortParams())
        }
        val descendants = Set[CommonA1RebuildProfile](profile, registeredRaw, factored, guarded, splitTag, buffered, CommonA1RebuildProfile.FullR1M3BufferedReturnFlow,
            CommonA1RebuildProfile.FullR1M3OrderedOwnerReady,
                CommonA1RebuildProfile.FullR1M3AdvisoryOwner,
                CommonA1RebuildProfile.FullR1M3CertifiedIngress,
                CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5,
                CommonA1RebuildProfile.FullR1M3ContextFetchPrefetchExperiment)
        for (old <- CommonA1RebuildProfile.all.filterNot(descendants.contains)) {
            assert(!old.config.elasticLoadProofSupply)
            old.memoryProfile.foreach { policy =>
                intercept[IllegalArgumentException] { policy.validate(candidate, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] {
            profile.memoryProfile.get.validate(control, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] { candidate.managedBoard() }
    }

    test("elastic proof supply cannot silently combine with another planner or ownership topology") {
        val c = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProof.config
        intercept[IllegalArgumentException] { c.copy(preparedHeadStoreOperands = false) }
        intercept[IllegalArgumentException] { c.copy(lsuEntries = 2) }
        intercept[IllegalArgumentException] { c.copy(virtualRamLoadPrecheck = false) }
        intercept[IllegalArgumentException] { c.copy(residentMemoryPayloadReuse = true) }
        intercept[IllegalArgumentException] { c.copy(preparedStoreLookahead = true) }
        intercept[IllegalArgumentException] { c.copy(memoryProofFrontier = true) }
        intercept[IllegalArgumentException] { c.copy(pendingVirtualStoreProof = true) }
        intercept[IllegalArgumentException] { c.copy(postedStoreMerge = true) }
        intercept[IllegalArgumentException] { c.copy(taggedStoreReturns = true) }
        val p = c.coreParams
        intercept[IllegalArgumentException] { p.copy(parallelMemoryPreparation = false) }
        intercept[IllegalArgumentException] { p.copy(parallelMemoryPayload = false) }
        intercept[IllegalArgumentException] { p.copy(registeredMemoryAddress = false) }
        intercept[IllegalArgumentException] { p.copy(memoryEntries = 2) }
    }

    test("elastic module retains separate lookup and permission registers with one new descriptor") {
        val p = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProof.config.coreParams
        val descriptorBits = p.robBits + p.tagBits + 64 + 2 + 32 + 1
        val certificateBits = p.robBits + p.tagBits + 64 + 2 + 64 + 32 + 1
        assert(descriptorBits == 167 && certificateBits == 231)
        assert(descriptorBits + certificateBits + 2 + certificateBits + 1 == 632)
        val fir = ChiselStage.emitCHIRRTL(new ElasticVirtualRamLoadPreparation(p))
        assert(fir.contains("descriptorValid") && fir.contains("translatedValid") && fir.contains("preparedValid"))
        assert(fir.contains("PmpChecker") && !fir.contains("SvTranslationService"))
        val legacy = ChiselStage.emitCHIRRTL(new VirtualRamLoadPreparation(
            CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRow.config.coreParams))
        assert(!legacy.contains("ElasticVirtualRamLoadPreparation") && !legacy.contains("descriptorValid"))
    }
}
