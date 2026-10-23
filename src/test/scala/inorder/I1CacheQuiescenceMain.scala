package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.core.inorder._
import soc.core.ooo.CacheTagConfig

/** Raw TL-C boundary for independently scheduled same-edge write/read/probe
  * collisions. No test-only memory or tag expectations enter the hardware.
  */
class I1CacheQuiescenceFixture(bytes: Int, missTurnover: Boolean = false) extends Module {
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new I1DataRequest))
        val response = Decoupled(new I1DataResponse)
        val flush = Input(Bool())
        val earlyPending = Input(Bool())
        val flushDone = Output(Bool())
        val quiescent = Output(Bool())
        val tl = new TLBundle(params)
        val native = new I1DataPort
    })
    val cache = Module(new I1CoherentLineCache(BigInt("80200000", 16), BigInt("80000000", 16),
        bytes / 64, params, ways = 2, tagConfig = CacheTagConfig.Aperture,
        controlTimingCuts = true, orderedDataAdmission = true, missTurnover = missTurnover, reportQuiescence = true))
    cache.io.upstream.request <> io.request; io.response <> cache.io.upstream.response
    cache.io.flushRequest := io.flush; io.flushDone := cache.io.flushDone
    cache.io.quiescenceRequestPending.get := io.request.valid || io.earlyPending
    io.quiescent := cache.io.quiescent.get
    io.tl <> cache.io.tl; io.native <> cache.io.downstream
}

object I1CacheQuiescenceMain extends App {
    val bytes = args.find(_.startsWith("--cache-bytes="))
        .map(_.stripPrefix("--cache-bytes=").toInt).getOrElse(32768)
    ChiselStage.emitCHIRRTLFile(new I1CacheQuiescenceFixture(bytes, args.contains("--miss-turnover")),
        Array("--target-dir", args.head))
}
