package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.ethernet._

class GmacRxAdmissionStopSpec extends AnyFunSuite {
    test("RX admission stop is an optional busy-safe CSR capability") {
        val old = ChiselStage.emitCHIRRTL(new TileLinkGmacControl())
        assert(!old.contains("rxStopRequest") && !old.contains("rxStopDrained"))
        val added = ChiselStage.emitCHIRRTL(new TileLinkGmacControl(GmacParams(rxAdmissionStop = true)))
        assert(added.contains("rxStopRequest") && added.contains("rxStopDrained"))
        assert(added.contains("rxStopWrite") && added.contains("commandLegal"))
    }
    test("producer barrier retains a mailbox acknowledgement and both ownership boundaries") {
        val fir = ChiselStage.emitCHIRRTL(new EthernetRxAdmissionStop)
        for (name <- Seq("CdcMailbox", "destinationFrameIdle", "destinationFifoIdle", "sourceDrained",
            "stopNewFrames", "settled", "drained")) assert(fir.contains(name))
        assert(!fir.contains("BUFGCE") && !fir.contains("EthernetPacketDma"))
    }
    test("native RX preserves its old ports unless admission-stop is requested") {
        intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new GmiiFrameRx(frameSlots = 3)))
        val old = ChiselStage.emitCHIRRTL(new GmiiFrameRx)
        assert(old.contains("occupied") && old.contains("producer") && old.contains("consumer"))
        assert(!old.contains("stopNewFrames") && !old.contains("ownedBusy"))
        val added = ChiselStage.emitCHIRRTL(new GmiiFrameRx(admissionStop = true))
        assert(added.contains("stopNewFrames") && added.contains("ownedBusy"))
    }
}
