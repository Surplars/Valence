package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class HeldAluIntegrationConfigSpec extends AnyFunSuite {
    test("A fields/order and all resources are exact under named false projection") {
        val off = HeldAluIntegrationProfile.off
        val on = HeldAluIntegrationProfile.on
        assert(HeldAluIntegrationProfile.historicalAFields(off).size == 88)
        assert(HeldAluIntegrationProfile.historicalAFields(off.coreParams).size == 172)
        assert(on.copy(heldAluIssueForwarding = false) == off)
        assert(on.coreParams.copy(heldAluIssueForwarding = false) == off.coreParams)
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!c.heldAluIssueForwarding)
        }
        intercept[IllegalArgumentException] { HeldAluIntegrationProfile.historicalAFields(on) }
        intercept[IllegalArgumentException] { HeldAluIntegrationProfile.historicalAFields(on.coreParams) }
        intercept[IllegalArgumentException] { NearTermAProfile.originalFields(NearTermAProfile.rollback.copy(heldAluIssueForwarding = true)) }
        intercept[IllegalArgumentException] { RetirementSlotProfile.original164(RetirementSlotProfile.p.copy(heldAluIssueForwarding = true)) }
        intercept[IllegalArgumentException] { PlacedTimingProfileBridge.publishedFields(on) }
    }
    test("every source topology guard rejects a single changed predicate") {
        val p = HeldAluIntegrationProfile.on.coreParams
        val mutations: Seq[() => OooParams] = Seq(
            () => p.copy(registeredIssueExecute = false), () => p.copy(registeredLoadIssueForwarding = false),
            () => p.copy(parallelIssuePayload = false), () => p.copy(parallelIssueRanks = false),
            () => p.copy(parallelRecoveryAdmission = false), () => p.copy(renameWidth = 1),
            () => p.copy(completionWidth = 1), () => p.copy(commitWidth = 1), () => p.copy(robEntries = 32),
            () => p.copy(physicalRegs = 64), () => p.copy(tagBits = 32), () => p.copy(moveAlias = true),
            () => p.copy(loadCompletionBypass = true), () => p.copy(mulWordPreviewBypass = true))
        mutations.foreach { change => intercept[IllegalArgumentException] { change() } }
        intercept[IllegalArgumentException] { OooParams(heldAluIssueForwarding = true) }
    }
    test("exact options and contradictory redundant constructor argument fail closed") {
        val flag = HeldAluIntegrationProfile.flag
        val options = HeldAluIntegrationProfile.offOptions
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(options ++ Seq(flag, flag)) }
        for (bad <- Seq("--held-alu", "--held-alu-issue-forward") ++ Seq("", "true", "false", "0", "1").map(flag + "=" + _)) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(options :+ bad) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(options.toSet + bad, false) }
        }
        HeldAluIntegrationActualAudit.requireArgument(HeldAluIntegrationProfile.on, true)
        HeldAluIntegrationActualAudit.requireArgument(HeldAluIntegrationProfile.off, false)
        intercept[IllegalArgumentException] { HeldAluIntegrationActualAudit.requireArgument(HeldAluIntegrationProfile.on, false) }
        intercept[IllegalArgumentException] { HeldAluIntegrationActualAudit.requireArgument(HeldAluIntegrationProfile.off, true) }
        // Actual constructor rejects before constructing its board or emitting hardware.
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new BoardSocGsim(configurationCheck = Some(HeldAluIntegrationProfile.on),
                heldAluIssueForwarding = false))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new BoardSocGsim(configurationCheck = Some(HeldAluIntegrationProfile.off),
                heldAluIssueForwarding = true))
        }
    }
}
