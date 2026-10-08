package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo.NonBlockingCoherentLineHome

class HomeMshrSpec extends AnyFunSuite {
    test("default fixture keeps old home and candidate has bounded independent ownership") {
        val legacy = ChiselStage.emitCHIRRTL(new HomeMshrGsim(1))
        assert(legacy.contains("module CoherentLineHome :"))
        assert(!legacy.contains("module NonBlockingCoherentLineHome"))
        for (entries <- Seq(2, 4)) {
            val fir = ChiselStage.emitCHIRRTL(new HomeMshrGsim(entries))
            assert(fir.contains("module NonBlockingCoherentLineHome"))
            assert(fir.contains(s"reg sources : UInt<3>[$entries]"))
            assert(fir.contains(s"reg directory : UInt<4>[$entries]"))
            assert(fir.contains("reg releaseData : UInt<64>[8]"))
            assert(!fir.contains("UInt<0>"))
        }
    }
    test("four sinks and bounded directory geometry are mandatory") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new NonBlockingCoherentLineHome(
                params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1), acquireEntries = 4))
        }
        for (entries <- Seq(1, 3, 8)) intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new NonBlockingCoherentLineHome(acquireEntries = entries))
        }
    }
}
