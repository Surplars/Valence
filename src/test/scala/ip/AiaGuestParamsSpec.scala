package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.interrupt._

class AiaGuestParamsSpec extends AnyFunSuite {
    test("guest targets reject impossible file counts and aliased pages") {
        for (n <- Seq(-1, 64)) intercept[IllegalArgumentException] { AplicParams(guestFiles = n) }
        intercept[IllegalArgumentException] { AplicParams(guestFiles = 3, msiBase = BigInt("28001000", 16)) }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new Aplic(AplicParams(guestFiles = 1)))
        }
    }
    test("supervisor guest bank configurations elaborate independently") {
        for (n <- Seq(0, 1, 2, 63)) {
            val rtl = ChiselStage.emitCHIRRTL(new Aplic(AplicParams(sources = 1, guestFiles = n,
                msiBase = BigInt("28000000", 16)), hasParent = true))
            assert(rtl.contains("module Aplic"))
        }
    }
}
