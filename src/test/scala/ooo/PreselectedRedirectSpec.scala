package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class PreselectedRedirectSpec extends AnyFunSuite {
    test("C0 adds no state or qualified configuration fields") {
        val p = ThreeProofRowNativeProfile.config.coreParams
        assert(p.productArity == 178 && ThreeProofRowNativeProfile.config.productArity == 95)
        assert(p.pendingVirtualStoreProofSlots == 3 && p.pendingStoreEarlyLoadCredits == 2)
        for (module <- Seq[() => chisel3.RawModule](
            () => new RedirectTokenQualification(p), () => new PreselectedRedirectTokenQualification(p))) {
            val fir = ChiselStage.emitCHIRRTL(module())
            assert(!fir.linesIterator.exists(line => line.trim.startsWith("reg ") || line.trim.startsWith("regreset ")))
        }
    }
}
