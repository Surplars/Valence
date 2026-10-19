package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.ip.tilelink.TileLinkClockDomainBoundary

class TileLinkClockDomainBoundarySpec extends AnyFunSuite {
    test("both storage profiles preserve five independent channels and identifier widths") {
        for (held <- Seq(false, true); (sources, sinks, depth) <- Seq((3, 1, if (held) 16 else 4), (4, 2, 8))) {
            val fir = ChiselStage.emitCHIRRTL(new TileLinkClockDomainBoundary(
                TLParams(addrWidth = 64, dataWidth = 64, sourceBits = sources, sinkBits = sinks),
                depth, heldResponseStorage = held))
            val fifo = if (held) "HeldResponseCdcDataFifo" else "CdcDataFifo"
            assert(fir.linesIterator.count(_.contains(s" of $fifo")) == 5)
            assert(fir.contains("cpuClock") && fir.contains("fabricClock"))
            assert(fir.contains("cpuTransportEmpty") && fir.contains("fabricTransportEmpty"))
            assert(fir.contains(s"source : UInt<$sources>"))
            assert(fir.contains(s"sink : UInt<$sinks>"))
            assert(fir.contains(s"[$depth]"))
            assert(!fir.contains("RegisterClockDomainBridge"))
            if (held) assert(!fir.linesIterator.exists(_.contains(" of CdcDataFifo")))
            else assert(!fir.contains("HeldResponseCdcDataFifo"))
        }
    }

    test("default storage remains the depth-four baseline") {
        val fir = ChiselStage.emitCHIRRTL(new TileLinkClockDomainBoundary(TLParams()))
        assert(fir.linesIterator.count(_.contains(" of CdcDataFifo")) == 5)
        assert(fir.contains("[4]"))
        assert(!fir.contains("HeldResponseCdcDataFifo"))
    }

    test("both storage profiles reject invalid FIFO capacity before elaboration") {
        for (held <- Seq(false, true); depth <- Seq(0, 1, 2, 3, 6)) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new TileLinkClockDomainBoundary(TLParams(), depth, heldResponseStorage = held))
            }
        }
    }
}
