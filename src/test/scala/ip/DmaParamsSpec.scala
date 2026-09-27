package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.dma.MemoryCopyDma

class DmaParamsSpec extends AnyFunSuite {
    test("DMA rejects invalid windows and elaborates relocated register and RAM regions") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MemoryCopyDma(base = 1)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MemoryCopyDma(ramBytes = 7)) }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MemoryCopyDma(ramBase = (BigInt(1) << 64) - 8))
        }
        val rtl = ChiselStage.emitCHIRRTL(new MemoryCopyDma(base = 0x2000, ramBase = 0x4000, ramBytes = 8))
        assert(rtl.contains("module MemoryCopyDma"))
    }
}
