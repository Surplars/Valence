package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.bus._
import soc.ip.ethernet._

class SelfGmacCdcSpec extends AnyFunSuite {
    test("CDC channels have explicit endpoints and reject invalid capacity") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new CdcDataFifo(0)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new CdcDataFifo(38, 3)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new CdcAccumulator(7)) }
        for (depth <- Seq(4, 16, 64)) {
            val fir = ChiselStage.emitCHIRRTL(new EthernetFrameClockBridge(depth))
            assert(fir.contains("sourceClock") && fir.contains("destinationClock"))
            assert(fir.contains("cmem") || fir.contains("mem"))
        }
    }
    test("native three-domain boundary has no CPU MAC or PHY dependency") {
        val fir = ChiselStage.emitCHIRRTL(new SelfGmacCdcTop)
        assert(fir.contains("CdcAccumulator") && fir.contains("PeripheralClockControl"))
        assert(!fir.contains("MachineCore") && !fir.contains("GmiiFrameTx") && !fir.contains("axi_ethernet"))
    }
    test("retention clock policy rejects unsafe watchdog parameters") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new PeripheralClockControl(7)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new PeripheralClockControl(8, 8)) }
        assert(ChiselStage.emitCHIRRTL(new PeripheralClockControl).contains("clockEnable"))
    }
}
