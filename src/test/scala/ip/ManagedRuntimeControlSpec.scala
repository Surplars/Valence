package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.ethernet.Rtl8211fPhyManager

class ManagedRuntimeControlSpec extends AnyFunSuite {
    test("PHY policy scheduling waits accept the positive boundary without changing MDIO timing") {
        for ((startup, poll) <- Seq((1, 1), (256, 512))) {
            val fir = ChiselStage.emitCHIRRTL(new Rtl8211fPhyManager(100000000,
                startupCycles = startup, pollCycles = poll, runtimePark = true))
            assert(fir.contains("module Rtl8211fPhyManager"))
            assert(fir.contains("parkRequest") && fir.contains("parked"))
        }
    }
    test("PHY policy scheduling rejects zero and negative waits") {
        for ((startup, poll) <- Seq((0, 1), (-1, 1), (1, 0), (1, -1))) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new Rtl8211fPhyManager(100000000,
                    startupCycles = startup, pollCycles = poll, runtimePark = true))
            }
        }
    }
}
