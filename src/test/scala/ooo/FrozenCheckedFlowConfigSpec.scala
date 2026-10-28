package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FrozenCheckedFlowConfigSpec extends AnyFunSuite {
    test("default OFF and only authoritative feature changes in the supported profile") {
        val base = PendingStoreProofFixture.params().copy(registeredCanonicalStoreEvent = true)
        assert(!OooParams().frozenStoreCheckedFlow && !base.frozenStoreCheckedFlow)
        val enabled = base.copy(frozenStoreCheckedFlow = true)
        assert(base.productElementNames.zip(base.productIterator).toMap.filterNot(_._1 == "frozenStoreCheckedFlow") ==
            enabled.productElementNames.zip(enabled.productIterator).toMap.filterNot(_._1 == "frozenStoreCheckedFlow"))
        assert(base.copy(frozenStoreCheckedFlow = true).copy(frozenStoreCheckedFlow = false) == base)
    }
    test("adapter derives canonical stage from OooParams and rejects missing checked boundary") {
        val p = PendingStoreProofFixture.params().copy(
            registeredCanonicalStoreEvent = true, frozenStoreCheckedFlow = true)
        // The canonical stage is no longer a second, independently supplied constructor flag.
        val canonical = ChiselStage.emitCHIRRTL {
            val adapter = new DataTranslationAdapter(p, registerCheckedRequests = true)
            assert(adapter.registerCanonicalStoreEvent)
            adapter
        }
        assert(canonical.contains("module DataTranslationAdapter"))
        val checked = intercept[Exception] {
            ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p))
        }
        assert(checked.toString.contains("frozen checked flow retains"))
    }
    test("reject missing bound producer or registered canonical event") {
        intercept[IllegalArgumentException] { OooParams(frozenStoreCheckedFlow = true) }
        intercept[IllegalArgumentException] {
            PendingStoreProofFixture.params().copy(frozenStoreCheckedFlow = true)
        }
        intercept[IllegalArgumentException] {
            PendingStoreProofFixture.params(enabled = false).copy(
                registeredCanonicalStoreEvent = true, frozenStoreCheckedFlow = true)
        }
    }
}
