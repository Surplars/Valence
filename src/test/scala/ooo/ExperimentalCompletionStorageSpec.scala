package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

/** Configuration/elaboration regression only; hardware behavior is checked separately with GSIM. */
class ExperimentalCompletionStorageSpec extends AnyFunSuite {
    private def emit(p: OooParams, experimental: Boolean, historical: Boolean = false): String =
        ChiselStage.emitCHIRRTL(new RenameRob(p, retirementSlotIdentity = p.retirementSlotIdentity,
            bankedCompletionPayload = historical, experimentalCompletionDataStorage = experimental))

    private def rejects(message: String)(body: => Any): Unit = {
        val error = intercept[IllegalArgumentException] { body }
        assert(error.getMessage.contains(message), s"unexpected rejection: ${error.getMessage}")
    }

    test("actual generic ROB16 and ROB32 retain default storage and expose only opt-in payload banking") {
        for ((rows, registers) <- Seq((16, 48), (32, 64))) {
            val profile = CommonCpuProfile.A1
            val config = CommonA1CpuSpec.resolve(profile, None,
                Some(CommonA1CpuSpec(4, rows, registers)), profile.boundary)
            val p = config.coreParams
            val before = p.copy()
            assert(p.robEntries == rows && p.physicalRegs == registers && p.memoryEntries == 4)
            assert(p.tagBits == 64 && !p.splitLowTagAdvance)
            assert(!p.bankedRobCompletionData && !config.bankedRobCompletionData)
            // Omit the new argument: this specifically checks the public constructor default.
            val baseline = ChiselStage.emitCHIRRTL {
                val ledger = new RenameRob(p, retirementSlotIdentity = p.retirementSlotIdentity)
                assert(!ledger.experimentalCompletionDataStorage)
                ledger
            }
            val candidate = emit(p, experimental = true)
            assert(!baseline.contains("module DualWriterRobCompletionData"))
            assert(candidate.contains("module DualWriterRobCompletionData"))
            assert(!candidate.contains("module WriterBankedRobCompletionPayload"))
            for (writer <- 0 until 2) {
                for (parity <- 0 until 2)
                    assert(candidate.contains(s"cmem completionWriter${writer}Parity$parity : UInt<128>[${rows / 2}]"))
                assert(candidate.contains(s"cmem tvalWriter$writer : UInt<64>[$rows]"))
            }
            // The recovery-query experiment must not enter either production elaboration.
            for (fir <- Seq(baseline, candidate)) {
                assert(fir.contains("module ParallelRecoveryAdmission"))
                assert(!fir.contains("output queries :"))
                assert(!fir.contains("QueriedRecoveryAdmission"))
            }
            assert(p == before && config.coreParams == before)
        }
        assert(!OooParams().bankedRobCompletionData && !FpgaNextConfig.Selected.bankedRobCompletionData)
        assert(!CommonCpuProfile.A1.fpga.bankedRobCompletionData)
    }

    test("isolated banking cannot silently enable or combine historical profiles") {
        val old = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3.config.coreParams
        assert(old.bankedRobCompletionData)
        rejects("isolated completion storage must not combine") { emit(old, experimental = true) }
        rejects("isolated completion storage must not combine") {
            emit(OooParams(), experimental = true, historical = true)
        }
        rejects("banked ROB completion data requires the exact second-efficiency") {
            OooParams(bankedRobCompletionData = true)
        }
        rejects("banked ROB completion data requires the exact second-efficiency") { old.copy(robEntries = 32) }
    }

    test("the constructor rejects incompatible writer reader and row geometry") {
        // Construct otherwise legal OooParams before checking constructor rejection:
        // configuration errors must not masquerade as the new storage guard.
        val incompatible = Seq(OooParams(completionWidth = 1), OooParams(completionWidth = 3),
            OooParams(commitWidth = 1), OooParams(commitWidth = 3),
            OooParams(robEntries = 2, recoveryWidth = 1))
        for (p <- incompatible) {
            rejects("completion data storage requires two writers, two consecutive readers and a power-of-two ROB") {
                emit(p, experimental = true)
            }
        }
    }
}
