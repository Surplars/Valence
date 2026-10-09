package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo.{AtomicDataMemory, MixedCoherentLineHome}
import soc.ip.dma.MemoryCopyDma

class DmaLineSpec extends AnyFunSuite {
    test("ordinary DMA and atomic interfaces remain default-off") {
        val dma = ChiselStage.emitCHIRRTL(new MemoryCopyDma)
        val atomic = ChiselStage.emitCHIRRTL(new AtomicDataMemory)
        assert(!dma.contains("line : {") && !atomic.contains("dmaLine : {"))
        val enabled = ChiselStage.emitCHIRRTL(new MemoryCopyDma(lineTransfers = true))
        assert(enabled.contains("line : {") && enabled.contains("reg payload : UInt<512>"))
        assert(enabled.contains("DMA line owner overlaps scalar traffic"))
        val gate = ChiselStage.emitCHIRRTL(new AtomicDataMemory(dmaLineTransfers = true))
        assert(gate.contains("dmaLine : {") && gate.contains("memoryLine : {"))
        assert(gate.contains("line DMA crossed atomic or ordinary ownership"))
    }
    test("dedicated DMA tags survive all supported bounded home geometries") {
        for (acquires <- Seq(2, 4); writes <- Seq(1, 2, 4)) {
            val fir = ChiselStage.emitCHIRRTL(new MixedCoherentLineHome(
                params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2),
                trackedLines = 16, acquireEntries = acquires, writebackEntries = writes,
                mixedReadWrite = true, dmaLineTransfers = true))
            val tagBits = math.max(chisel3.util.log2Ceil(acquires + 1), chisel3.util.log2Ceil(writes + 2))
            assert(fir.contains(s"tag : UInt<$tagBits>"))
            assert(fir.contains("DMA read result lost its line owner"))
            assert(fir.contains("DMA write result lost its line owner"))
            assert(fir.contains("home read result has an unknown full tag"))
            assert(!fir.contains("UInt<0>"))
        }
    }
    test("yield uses a small countdown and preserves the line-owner contract") {
        for (cycles <- Seq(4, 16)) {
            val fir = ChiselStage.emitCHIRRTL(new MemoryCopyDma(lineTransfers = true, lineYieldCycles = cycles))
            assert(fir.contains(s"regreset quiet : UInt<${chisel3.util.log2Ceil(cycles + 1)}>"))
            assert(fir.contains("DMA line owner overlaps scalar traffic"))
        }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MemoryCopyDma(lineYieldCycles = 4)) }
    }

}
