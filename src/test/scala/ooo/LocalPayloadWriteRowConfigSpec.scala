package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class LocalPayloadWriteRowConfigSpec extends AnyFunSuite {
    test("upper payload row option defaults off") {
        ChiselStage.emitCHIRRTL {
            val dut = new TileLinkAxi4Bridge()
            assert(!dut.localPayloadWriteRow)
            dut
        }
    }
    test("wrapper propagates row option to the actual manager and every slot") {
        for (local <- Seq(false, true)) {
            ChiselStage.emitCHIRRTL {
                val dut = new TileLinkAxi4Bridge(
                    axiAddressWidth = 32, axiIdWidth = 4,
                    axiAddressBase = BigInt("80200000", 16), axiWindowBytes = BigInt(1) << 31,
                    maxOutstanding = 4, maxOutstandingWrites = 2, unorderedResponses = true,
                    writeCollectionFlow = true, lineReadChannel = true,
                    localPayloadWriteEnable = true, localPayloadWriteRow = local)
                val manager = dut.outstandingInstance.get
                assert(manager.localPayloadWriteRow == local)
                assert(manager.slots.forall(_.localPayloadWriteRow == local))
                dut
            }
        }
    }
    test("row localization rejects absent line banks or absent localized enables") {
        for (line <- Seq(false, true); enable <- Seq(false, true) if !(line && enable)) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new TileLinkAxi4BurstBridge(
                    axiWindowBytes = BigInt(1) << 31, lineReadChannel = line,
                    localPayloadWriteEnable = enable, localPayloadWriteRow = true))
            }
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new TileLinkAxi4Bridge(
                    lineReadChannel = line, localPayloadWriteEnable = enable, localPayloadWriteRow = true))
            }
        }
    }
}
