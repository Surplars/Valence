package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class EfficiencyRefactorSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon
    private val candidate = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor

    test("efficiency candidate is explicit and all historical profiles keep features disabled") {
        assert(candidate.config == control.config.copy(canonicalFetchCacheKeys = true,
            registeredMemoryOperandCapture = true, sharedMulDivOperandReads = true,
            sourceLocalLoadProofCancellation = true, sharedLoadProofPmpBounds = true,
            branchPredictorEntriesOverride = Some(256)))
        assert(candidate.config.coreParams == control.config.coreParams.copy(canonicalFetchCacheKeys = true,
            registeredMemoryOperandCapture = true, sharedMulDivOperandReads = true,
            sourceLocalLoadProofCancellation = true, sharedLoadProofPmpBounds = true,
            branchPredictorEntries = 256))
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        for (profile <- CommonA1RebuildProfile.all) {
            val enabled = profile == candidate || profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2 ||
                profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3 ||
                profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4 ||
                profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5 ||
                profile == CommonA1RebuildProfile.FullR1M3MulLoadOperandCaptureExperiment ||
                profile == CommonA1RebuildProfile.FullR1M3ContextFetchPrefetchExperiment
            val c = profile.config
            val p = c.coreParams
            assert(c.canonicalFetchCacheKeys == enabled && p.canonicalFetchCacheKeys == enabled)
            assert(c.registeredMemoryOperandCapture == enabled && p.registeredMemoryOperandCapture == enabled)
            assert(c.sharedMulDivOperandReads == enabled && p.sharedMulDivOperandReads == enabled)
            assert(c.sourceLocalLoadProofCancellation == enabled && p.sourceLocalLoadProofCancellation == enabled)
            assert(c.sharedLoadProofPmpBounds == enabled && p.sharedLoadProofPmpBounds == enabled)
            assert(c.branchPredictorEntriesOverride == (if (enabled) Some(256) else None))
        }
        val d = OooParams()
        assert(!d.canonicalFetchCacheKeys && !d.registeredMemoryOperandCapture &&
            !d.sharedMulDivOperandReads && !d.sourceLocalLoadProofCancellation && !d.sharedLoadProofPmpBounds)
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
    }

    test("strict candidate policy cannot leak into any historical policy") {
        val policy = candidate.memoryProfile.get
        policy.validate(candidate.config, CommonCpuTilePortParams())
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            intercept[IllegalArgumentException] { policy.validate(old.config, CommonCpuTilePortParams()) }
            old.memoryProfile.foreach { previous =>
                intercept[IllegalArgumentException] { previous.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
    }

    test("unqualified operand and proof topologies are rejected at configuration boundary") {
        val p = candidate.config.coreParams
        for (bad <- Seq[() => OooParams](
            () => OooParams(registeredMemoryOperandCapture = true),
            () => OooParams(sharedMulDivOperandReads = true),
            () => OooParams(sourceLocalLoadProofCancellation = true),
            () => OooParams(sharedLoadProofPmpBounds = true),
            () => OooParams(canonicalFetchCacheKeys = true),
            () => p.copy(ownerLocalOperandReady = false),
            () => p.copy(parallelPrfReadyUpdates = false),
            () => p.copy(registeredLoadIssueForwarding = false),
            () => p.copy(parallelMulDivDispatch = false),
            () => p.copy(earlyStorePreparation = false),
            () => p.copy(sharedStoreOperandReads = false),
            () => p.copy(loadCompletionBypass = true))) {
            intercept[IllegalArgumentException] { bad() }
        }
        for (n <- Seq(0, 1, 3, 257, 512)) {
            intercept[IllegalArgumentException] { candidate.config.copy(branchPredictorEntriesOverride = Some(n)) }
        }
        intercept[IllegalArgumentException] { FpgaNextConfig(branchPredictorEntriesOverride = Some(256)) }
    }
}
