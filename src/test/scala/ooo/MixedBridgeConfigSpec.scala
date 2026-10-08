package ooo

import org.scalatest.funsuite.AnyFunSuite
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.core.ooo._

class MixedBridgeConfigSpec extends AnyFunSuite {
    test("mixed read write geometry is explicit and bounded by source ownership") {
        assert(DdrBridgeConfig.Legacy.maxOutstandingWrites == 0)
        assert(!CoherentCacheConcurrency().overlapWritebackRefill)
        for ((slots, writes) <- Seq((4, 2), (8, 2), (8, 4))) {
            val c = DdrBridgeConfig(maxOutstanding = slots, maxOutstandingWrites = writes)
            c.validateSoc(); c.validateTileLink(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3))
            val fir = ChiselStage.emitCHIRRTL(new TileLinkAxi4Bridge(
                tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3), axiIdWidth = 4,
                axiWindowBytes = BigInt(1) << 31, maxOutstanding = slots, maxOutstandingWrites = writes))
            assert(fir.contains("writeOrder"))
        }
        for ((reads, writes) <- Seq((2, 2), (4, 2), (4, 4))) {
            val c = CoherentCacheConcurrency(reads, reads, writes, overlapWritebackRefill = true)
            assert(c.sourceBits == (if (reads + writes <= 4) 2 else 3))
            assert(c.releaseSource + writes <= (1 << c.sourceBits))
        }
        intercept[IllegalArgumentException] { DdrBridgeConfig(maxOutstanding = 4, maxOutstandingWrites = 5) }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(1, 2, 2) }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(2, 2, 3) }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(2, 2, 1, true) }
    }
    test("mixed memory keyed options compose and reject duplicate illegal capacity") {
        val (rest, options) = MixedMemoryConfig.parseArgs(Array("out", "ddr", "--banked-rob",
            "--ddr-write-slots=2", "--cache-writebacks=2", "--overlap-writeback-refill"))
        assert(rest.sameElements(Array("out", "ddr", "--banked-rob")))
        assert(options.ddr(DdrBridgeConfig(maxOutstanding = 4)).maxOutstandingWrites == 2)
        assert(options.cache(CoherentCacheConcurrency(2)).overlapWritebackRefill)
        intercept[IllegalArgumentException] { options.ddr(DdrBridgeConfig()) }
        intercept[IllegalArgumentException] { options.cache(CoherentCacheConcurrency(2), sourceBits = 1) }
        intercept[IllegalArgumentException] { options.cache(CoherentCacheConcurrency()) }
        for (bad <- Seq(Array("--ddr-write-slots=2", "--ddr-write-slots=2"),
            Array("--cache-writebacks=2", "--cache-writebacks=4"), Array("--cache-writebacks=3"),
            Array("--ddr-write-slots=-1"), Array("--ddr-write-slots=9"), Array("--ddr-write-slots"),
            Array("--overlap-writeback-refill", "--overlap-writeback-refill"), Array("--overlap-writeback-refill=0"))) {
            intercept[IllegalArgumentException] { MixedMemoryConfig.parseArgs(bad) }
        }
        assert(!MixedMemoryConfig.parseArgs(Array("out"))._2.specified)
    }
    test("unordered DDR responses are explicitly parsed and bounded") {
        val (rest, opts) = MixedMemoryConfig.parseArgs(Array("out", "--unordered-ddr-responses"))
        assert(rest.sameElements(Array("out")))
        assert(opts.specified && opts.ddr(DdrBridgeConfig(maxOutstanding = 4)).unorderedResponses)
        assert(!DdrBridgeConfig.Legacy.unorderedResponses)
        intercept[IllegalArgumentException] { DdrBridgeConfig(unorderedResponses = true) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new TileLinkAxi4Bridge(
            unorderedResponses = true, axiWindowBytes = 4096)) }
        intercept[IllegalArgumentException] { MixedMemoryConfig.parseArgs(Array("--unordered-ddr-responses", "--unordered-ddr-responses")) }
        intercept[IllegalArgumentException] { MixedMemoryConfig.parseArgs(Array("--unordered-ddr-responses=1")) }
    }
}
