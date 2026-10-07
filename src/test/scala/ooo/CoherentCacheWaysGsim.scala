package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Independent manager lives in the C++ driver; no DUT-derived memory oracle. */
class CoherentCacheWaysGsim(ways: Int, lines: Int = 4) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val tl = new soc.bus.tilelink.TLBundle(
            soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3))
        val flushRequest = Input(Bool())
        val flushDone = Output(Bool())
        val hit = Output(Bool())
        val miss = Output(Bool())
    })
    val cache = Module(new CoherentLineCache(lines = lines, ways = ways))
    io.upstream <> cache.io.upstream
    io.downstream <> cache.io.downstream
    io.tl <> cache.io.tl
    cache.io.flushRequest := io.flushRequest
    io.flushDone := cache.io.flushDone
    io.hit := cache.io.hit
    io.miss := cache.io.miss
}
object CoherentCacheWaysGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CoherentCacheWaysGsim(args(1).toInt, args.lift(2).map(_.toInt).getOrElse(4)),
        Array("--target-dir", args.head))
}
