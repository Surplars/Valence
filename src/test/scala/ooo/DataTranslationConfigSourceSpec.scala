package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Configuration API checks, not a substitute for cycle/permission equivalence. */
class DataTranslationConfigSourceSpec extends AnyFunSuite {
    test("canonical staging and checked hint factoring independently follow OooParams") {
        for (canonical <- Seq(false, true); factoring <- Seq(false, true)) {
            val p = PendingStoreProofFixture.params().copy(
                registeredCanonicalStoreEvent = canonical,
                dataNextLinePrefetch = true, factorCheckedNextAllowed = factoring)
            val rtl = ChiselStage.emitCHIRRTL {
                val adapter = new DataTranslationAdapter(p, registerCheckedRequests = true)
                assert(adapter.registerCanonicalStoreEvent == canonical)
                assert(adapter.factorCheckedNextAllowed == factoring)
                adapter
            }
            assert(rtl.contains("module DataTranslationAdapter"))
        }
    }

    test("checked hint factoring still rejects a missing checked register") {
        val p = PendingStoreProofFixture.params().copy(
            dataNextLinePrefetch = true, factorCheckedNextAllowed = true)
        val error = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p))
        }
        assert(error.getMessage.contains("checked hint factoring requires the non-flow checked queue"))
    }

    test("canonical and hint prerequisites remain enforced in the single configuration source") {
        intercept[IllegalArgumentException] { OooParams(registeredCanonicalStoreEvent = true) }
        intercept[IllegalArgumentException] { OooParams(factorCheckedNextAllowed = true) }
    }
}
