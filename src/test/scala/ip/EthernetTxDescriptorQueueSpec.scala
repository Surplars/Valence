package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.dma.EthernetTxDescriptorQueue

class EthernetTxDescriptorQueueSpec extends AnyFunSuite {
    test("posted TX derived fields support subword lengths and unaligned aperture limits") {
        for ((base, bytes, maxLength) <- Seq(
            (BigInt(0), BigInt(1), 1),
            (BigInt(1), BigInt(30), 3),
            (BigInt(0), BigInt(32), 8),
            (BigInt("80200000", 16), BigInt(1) << 31, 2048),
            ((BigInt(1) << 64) - 4096, BigInt(4096), 2048))) {
            val rtl = ChiselStage.emitCHIRRTL(new EthernetTxDescriptorQueue(1, base, bytes, maxLength))
            assert(rtl.contains("stageLengthValid"))
            assert(rtl.contains("stageWords"))
            assert(rtl.contains("endWord"))
        }
    }
    test("independent STOP admission has an explicit transport-qualified input") {
        val rtl = ChiselStage.emitCHIRRTL(new EthernetTxDescriptorQueue(
            4, BigInt("80200000", 16), BigInt(1) << 31, 2048,
            runtimeAdmission = true, separateStopAcceptance = true))
        assert(rtl.contains("acceptedWrite"))
        assert(rtl.contains("acceptedStop"))
        assert(rtl.contains("independent STOP acceptance disagrees"))
    }
}
