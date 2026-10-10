package ooo

import org.scalatest.funsuite.AnyFunSuite
import _root_.circt.stage.ChiselStage

class PostedStoreHomeRebuildSpec extends AnyFunSuite {
    test("real-home wrapper selects actual ownership and AXI components with explicit posted ON/OFF") {
        for (enabled <- Seq(false, true)) {
            val fir = ChiselStage.emitCHIRRTL(new PostedStoreHomeGsim(enabled))
            assert(fir.contains("module MixedCoherentLineHome"))
            assert(fir.contains("module AtomicDataMemory"))
            assert(fir.contains("module TileLinkAxi4OutstandingBridge"))
            assert(fir.contains("module PostedStoreMerge") == enabled)
            assert(fir.contains("holdReleaseAck"))
        }
    }
}
