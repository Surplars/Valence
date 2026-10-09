package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo.{AtomicDataMemory, MixedCoherentLineHome}
import soc.ip.dma.MemoryCopyDma

class DmaOverlapSpec extends AnyFunSuite {
    test("tag classes retain boundary carries at two and four line owners") {
        for (depth <- Seq(2, 4); acquires <- Seq(2, 4); writes <- Seq(1, 2, 4)) {
            val bits = math.max(chisel3.util.log2Ceil(acquires + depth), chisel3.util.log2Ceil(writes + depth + 1))
            val readTags = (acquires until acquires + depth).toSet
            val writeTags = (writes + 1 until writes + 1 + depth).toSet
            assert(readTags.intersect((0 until acquires).toSet).isEmpty)
            assert(writeTags.intersect((0 to writes).toSet).isEmpty)
            assert((readTags ++ writeTags).forall(_ < (1 << bits)))
            val fir = ChiselStage.emitCHIRRTL(new MixedCoherentLineHome(
                params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2),
                trackedLines = 16, acquireEntries = acquires, writebackEntries = writes,
                mixedReadWrite = true, dmaLineTransfers = true, dmaLineEntries = depth))
            assert(fir.contains(s"tag : UInt<$bits>"))
            assert(fir.contains(s"add(UInt<$bits>(0h${acquires.toHexString}), accessTag)"),
                "read dispatch adder must retain the high tag-class bit")
            assert(fir.contains(s"add(UInt<$bits>(0h${(writes + 1).toHexString}), accessTag)"),
                "write dispatch adder must retain the release/DMA boundary carry")
            assert(fir.contains("DMA read tag overlaps refill tag class"))
            assert(fir.contains("DMA write tag overlaps release/probe tag class"))
            assert(fir.contains("home line response lost read/write owner"))
            assert(!fir.contains("UInt<0>"))
        }
    }
    test("bounded slots retain payload offsets and atomic owners") {
        for (depth <- Seq(2, 4)) {
            val dma = ChiselStage.emitCHIRRTL(new MemoryCopyDma(lineTransfers = true, lineEntries = depth))
            val atomic = ChiselStage.emitCHIRRTL(new AtomicDataMemory(dmaLineTransfers = true, dmaLineEntries = depth))
            assert(dma.contains(s"payloads : UInt<512>[$depth]"))
            assert(dma.contains("pipelined DMA response has no retained owner"))
            assert(atomic.contains("atomic line tag reused before response"))
            assert(atomic.contains("line DMA crossed atomic or ordinary ownership"))
        }
    }
}
