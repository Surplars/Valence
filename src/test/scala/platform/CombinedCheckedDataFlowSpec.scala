package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class CombinedCheckedDataFlowSpec extends AnyFunSuite {
    test("combined checked policy changes only the two explicit flags from full-r1-m3") {
        val control = CommonA1RebuildProfile.FullR1M3.config
        val candidate = CommonA1RebuildProfile.FullR1M3CheckedFlow.config
        assert(!OooParams().combinedCheckedDataFlow)
        assert(!FpgaNextConfig.Selected.combinedCheckedDataFlow)
        assert(!CommonCpuProfile.A1.fpga.combinedCheckedDataFlow)
        assert(candidate == control.copy(precheckedDataRequestFlow = true, combinedCheckedDataFlow = true))
        assert(candidate.coreParams == control.coreParams.copy(
            precheckedDataRequestFlow = true, combinedCheckedDataFlow = true))
        assert(candidate.translationHitFlow && control.translationHitFlow)
        assert(candidate.cache == control.cache && candidate.ddr == control.ddr)
        assert(candidate.name != control.name)
        assert(CommonA1RebuildProfile.named("full-r1-m3-checked-flow") == CommonA1RebuildProfile.FullR1M3CheckedFlow)
        CommonA1RebuildProfile.FullR1M3CheckedFlow.memoryProfile.get.validate(candidate, CommonCpuTilePortParams())
        intercept[IllegalArgumentException] {
            CommonA1RebuildProfile.FullR1M3.memoryProfile.get.validate(candidate, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] {
            CommonA1RebuildProfile.FullR1M3CheckedFlow.memoryProfile.get.validate(control, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] { candidate.managedBoard() }
    }

    test("old separate flow combinations remain legal and an implicit combination remains rejected") {
        val base = FpgaNextConfig.Selected.copy(virtualRamLoadPrecheck = true)
        assert(base.copy(precheckedDataRequestFlow = true).coreParams.precheckedDataRequestFlow)
        assert(base.copy(translationHitFlow = true).translationHitFlow)
        intercept[IllegalArgumentException] {
            base.copy(precheckedDataRequestFlow = true, translationHitFlow = true)
        }
        val on = CommonA1RebuildProfile.FullR1M3CheckedFlow.config
        intercept[IllegalArgumentException] { on.copy(combinedCheckedDataFlow = false) }
        intercept[IllegalArgumentException] { on.copy(translationHitFlow = false) }
        intercept[IllegalArgumentException] { on.copy(precheckedDataRequestFlow = false) }
        intercept[IllegalArgumentException] { on.copy(canonicalVirtualStoreOverlap = false) }
        intercept[IllegalArgumentException] { on.copy(queuedHeadSelection = true) }
        intercept[IllegalArgumentException] { on.copy(registeredCanonicalStoreEvent = true) }
        intercept[IllegalArgumentException] { on.copy(registeredDataTranslation = true) }
        intercept[IllegalArgumentException] { on.copy(physicalLoadIngressFlow = true) }
        intercept[IllegalArgumentException] { on.copy(translatedResponseEmptyFlow = true) }
        intercept[IllegalArgumentException] { on.copy(taggedStoreReturns = true) }
        intercept[IllegalArgumentException] { on.copy(postedStoreMerge = true) }
        intercept[IllegalArgumentException] { on.copy(frozenStoreProofTransport = true) }
        intercept[IllegalArgumentException] { on.copy(pendingVirtualStoreProof = true) }
        val p = on.coreParams
        intercept[IllegalArgumentException] { p.copy(registeredTranslationHeads = false) }
        intercept[IllegalArgumentException] { p.copy(precheckedDataRequestFlow = false) }
        intercept[IllegalArgumentException] { p.copy(canonicalVirtualStoreOverlap = false) }
        intercept[IllegalArgumentException] { p.copy(registeredMemoryRequests = false) }
    }

    test("actual combined adapter retains both checked paths and rejects missing constructor authorization") {
        val candidate = CommonA1RebuildProfile.FullR1M3CheckedFlow.config
        val p = candidate.coreParams
        def emit(q: OooParams, checked: Boolean = true, hit: Boolean = true): String =
            ChiselStage.emitCHIRRTL(new DataTranslationAdapter(q, registerCheckedRequests = checked,
                translationHitFlow = hit, registerCanonicalStoreEvent = q.registeredCanonicalStoreEvent,
                queuedHeadSelection = q.queuedHeadSelection, alignedNextLinePmp = q.alignedNextLinePmp,
                factorCheckedNextAllowed = q.factorCheckedNextAllowed))
        val fir = emit(p)
        assert(fir.contains("combined immediate ingress transfers exactly once"))
        assert(fir.contains("combined blocked certified PA spills exactly once"))
        assert(fir.contains("combined canonical event belongs only"))
        assert(fir.contains("translated") && fir.contains("checked") && fir.contains("virtualRequests"))
        val off = emit(CommonA1RebuildProfile.FullR1M3.config.coreParams)
        assert(!off.contains("combined immediate ingress transfers exactly once"))
        intercept[IllegalArgumentException] { emit(p, hit = false) }
        intercept[IllegalArgumentException] { emit(p, checked = false) }
        intercept[IllegalArgumentException] { emit(p.copy(combinedCheckedDataFlow = false)) }
    }
}
