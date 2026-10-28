package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class RegisteredRawCertifiedFlowSpec extends AnyFunSuite {
    private val controlProfile = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProof
    private val profile = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofRegisteredRaw

    test("registered raw/certified policy changes only its explicit source routes") {
        val control = controlProfile.config
        val candidate = profile.config
        assert(!OooParams().registeredRawCertifiedFlow && !FpgaNextConfig.Selected.registeredRawCertifiedFlow)
        assert(!CommonCpuProfile.A1.fpga.registeredRawCertifiedFlow)
        assert(candidate == control.copy(registeredRawCertifiedFlow = true, registeredDataTranslation = true,
            translationHitFlow = false, combinedCheckedDataFlow = false))
        assert(candidate.coreParams == control.coreParams.copy(registeredRawCertifiedFlow = true,
            registeredDataTranslation = true, combinedCheckedDataFlow = false))
        assert(candidate.precheckedDataRequestFlow && candidate.elasticLoadProofSupply &&
            candidate.preparedHeadStoreOperands && candidate.completedCanonicalStoreForwarding)
        assert(candidate.cache == control.cache && candidate.ddr == control.ddr)
        assert(candidate.name != control.name && candidate.coreParams.memoryEntries == 4)
        assert(CommonA1RebuildProfile.named(profile.name) == profile)
        profile.memoryProfile.get.validate(candidate, CommonCpuTilePortParams())
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == profile)) {
            assert(!old.config.registeredRawCertifiedFlow)
            old.memoryProfile.foreach { policy =>
                intercept[IllegalArgumentException] { policy.validate(candidate, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] {
            profile.memoryProfile.get.validate(control, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] { candidate.managedBoard() }
    }

    test("old M2 and combined legality stay isolated from the new explicit mode") {
        val m2 = CommonA1RebuildProfile.FullM2.config
        assert(m2.registeredDataTranslation && !m2.precheckedDataRequestFlow && !m2.translationHitFlow)
        intercept[IllegalArgumentException] { m2.copy(precheckedDataRequestFlow = true).coreParams }
        val combined = controlProfile.config
        intercept[IllegalArgumentException] { combined.copy(translationHitFlow = false) }
        intercept[IllegalArgumentException] { combined.copy(registeredDataTranslation = true) }
        val c = profile.config
        intercept[IllegalArgumentException] { c.copy(registeredRawCertifiedFlow = false) }
        intercept[IllegalArgumentException] { c.copy(registeredDataTranslation = false) }
        intercept[IllegalArgumentException] { c.copy(precheckedDataRequestFlow = false) }
        intercept[IllegalArgumentException] { c.copy(translationHitFlow = true) }
        intercept[IllegalArgumentException] { c.copy(combinedCheckedDataFlow = true) }
        intercept[IllegalArgumentException] { c.copy(queuedHeadSelection = true) }
        intercept[IllegalArgumentException] { c.copy(physicalLoadIngressFlow = true) }
        intercept[IllegalArgumentException] { c.copy(translatedResponseEmptyFlow = true) }
        intercept[IllegalArgumentException] { c.copy(registeredCanonicalStoreEvent = true) }
        intercept[IllegalArgumentException] { c.copy(postedStoreMerge = true) }
        intercept[IllegalArgumentException] { c.copy(taggedStoreReturns = true) }
        intercept[IllegalArgumentException] { c.copy(frozenStoreProofTransport = true) }
        val p = c.coreParams
        intercept[IllegalArgumentException] { p.copy(registeredTranslationHeads = false) }
        intercept[IllegalArgumentException] { p.copy(registeredMemoryRequests = false) }
    }

    test("actual adapter retains registered raw results and a separately authorized certified source") {
        def emit(p: OooParams, checked: Boolean = true, hit: Boolean = false): String =
            ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p, registerCheckedRequests = checked,
                translationHitFlow = hit,
                queuedHeadSelection = p.queuedHeadSelection, alignedNextLinePmp = p.alignedNextLinePmp))
        val p = profile.config.coreParams
        val fir = emit(p)
        assert(fir.contains("DataTranslationResultBuffer") && fir.contains("DataPhysicalPermissionEvaluator"))
        assert(fir.contains("registered raw demand never bypasses"))
        assert(fir.contains("certified checked transfer uses only its registered ingress descriptor"))
        assert(fir.contains("registered raw canonical event belongs only to the accepted FIFO head"))
        assert(fir.contains("combined immediate ingress transfers exactly once"))
        val oldM2 = emit(CommonA1RebuildProfile.FullM2.config.coreParams)
        assert(!oldM2.contains("registered raw demand never bypasses"))
        val oldCombined = emit(controlProfile.config.coreParams, hit = true)
        assert(!oldCombined.contains("DataPhysicalPermissionEvaluator"))
        assert(!oldCombined.contains("registered raw demand never bypasses"))
        intercept[IllegalArgumentException] { emit(p, checked = false) }
        intercept[IllegalArgumentException] { emit(p, hit = true) }
    }
}
