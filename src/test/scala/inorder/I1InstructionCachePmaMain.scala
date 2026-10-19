package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.core.inorder._

/** Real read-only cache/native adapter, with externally driven TL-C and
  * scalar replies. No DUT memory or tag state supplies expected test data.
  */
class I1InstructionCachePmaFixture(bytes: Int, predecode: Boolean = false) extends Module {
    val p = FiveStageConfig(pipelineProfile = "fpga8", fpgaTimingCuts = true, xlen = 64,
        instructionCacheBytes = bytes, dataCacheBytes = bytes, coherentCaches = true,
        coherentControlCuts = true, coherentCacheWays = 2, coherentBandwidth = true,
        withC = predecode, cacheFetchPredecode = predecode,
        cacheableBase = BigInt("80200000", 16), cacheableBytes = BigInt("80000000", 16))
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val response = Decoupled(new FiveStageDataResponse(p))
        val readCacheable = Input(Bool())
        val invalidate = Input(Bool())
        val tl = new TLBundle(params)
        val native = new I1DataPort
    })
    val cache = Module(new FiveStageWordCache(p, bytes, allowHitReplacement = true,
        trustedReadOnlyCacheability = true))
    cache.io.request <> io.request; io.response <> cache.io.response
    cache.io.readCacheable.get := io.readCacheable
    cache.io.invalidate := io.invalidate
    io.tl <> cache.io.coherence.get; io.native <> cache.io.uncached.get
    cache.io.memory.request.ready := false.B
    cache.io.memory.response.valid := false.B
    cache.io.memory.response.bits := 0.U.asTypeOf(cache.io.memory.response.bits)
    assert(!cache.io.memory.request.valid, "coherent IF must not use noncoherent backing")
}

object I1InstructionCachePmaMain extends App {
    val bytes = args.find(_.startsWith("--cache-bytes="))
        .map(_.stripPrefix("--cache-bytes=").toInt).getOrElse(32768)
    ChiselStage.emitCHIRRTLFile(new I1InstructionCachePmaFixture(bytes, args.contains("--predecode")), Array("--target-dir", args.head))
}
