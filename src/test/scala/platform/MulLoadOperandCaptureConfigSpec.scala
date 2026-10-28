package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{FpgaNextConfig, OooParams}
import soc.platform._

/** Pure configuration checks only; no elaboration or hardware simulation. */
class MulLoadOperandCaptureConfigSpec extends AnyFunSuite {
    private val baseline = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4
    private val candidate = CommonA1RebuildProfile.FullR1M3MulLoadOperandCaptureExperiment

    test("MUL registered-load capture is default OFF and leaves every prior profile OFF") {
        assert(!OooParams().registeredMulLoadOperandCapture)
        assert(!FpgaNextConfig().registeredMulLoadOperandCapture)
        for (profile <- CommonA1RebuildProfile.all if profile != candidate) {
            assert(!profile.config.registeredMulLoadOperandCapture)
            assert(!profile.config.coreParams.registeredMulLoadOperandCapture)
        }
    }

    test("the new explicit experiment differs from fourth control in exactly one capability") {
        val control = baseline.config
        val experiment = candidate.config
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        assert(experiment.registeredMulLoadOperandCapture)
        assert(experiment.copy(registeredMulLoadOperandCapture = false) == control)
        assert(experiment.coreParams.copy(registeredMulLoadOperandCapture = false) == control.coreParams)
        assert(!experiment.contextOwnedInstructionPrefetch && !experiment.loadPayloadNomination)
        assert(candidate.memoryProfile.contains(CommonA1MemoryProfile.ExperimentalMulLoadOperandCapture))
        candidate.memoryProfile.get.validate(experiment, CommonCpuTilePortParams())
        intercept[IllegalArgumentException] {
            CommonA1MemoryProfile.ExperimentalEfficiencyRefactor4.validate(experiment, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] {
            CommonA1MemoryProfile.ExperimentalMulLoadOperandCapture.validate(control, CommonCpuTilePortParams())
        }
    }

    test("the experiment rejects missing capture boundaries and mixed speculative profiles") {
        val config = candidate.config
        val p = config.coreParams
        val unsupported = Seq[OooParams => OooParams](
            _.copy(sharedMulDivOperandReads = false),
            _.copy(registeredMulDivOperands = false),
            _.copy(registeredLoadIssueForwarding = false),
            _.copy(registeredMemoryOperandCapture = false),
            _.copy(ownerLocalOperandReady = false),
            _.copy(parallelPrfReadyUpdates = false),
            _.copy(tagBits = 32),
            _.copy(loadCompletionBypass = true),
            _.copy(registeredLoadResultReady = true),
            _.copy(mulWordPreviewBypass = true),
            _.copy(fastHeadLoadRetire = true),
            _.copy(contextOwnedInstructionPrefetch = true),
            _.copy(loadPayloadNomination = true))
        for (change <- unsupported) intercept[IllegalArgumentException] { change(p) }
        intercept[IllegalArgumentException] { config.copy(contextOwnedInstructionPrefetch = true) }
        intercept[IllegalArgumentException] { config.copy(loadPayloadNomination = true) }
        intercept[IllegalArgumentException] { config.managedBoard() }
    }
}
