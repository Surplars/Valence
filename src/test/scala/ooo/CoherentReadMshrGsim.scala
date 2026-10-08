package ooo

import chisel3._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo._

/** Independent manager, storage and CPU response oracle live entirely in C++. */
class CoherentReadMshrGsim(mshrs: Int = 2, lines: Int = 512, ways: Int = 2, responses: Int = 8,
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth, base: BigInt = BigInt("80010000", 16)) extends Module {
    private val cfg = CoherentCacheConcurrency(mshrs, responses)
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = cfg.sinkBits)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val tl = new TLBundle(params)
        val flushRequest = Input(Bool())
        val flushDone = Output(Bool())
        val hit = Output(Bool())
        val miss = Output(Bool())
        val mshrOccupancy = Output(UInt(3.W))
    })
    val cache = CoherentLineCacheModule.build(base, math.max(16384, lines * 256),
        lines, params, ways, cfg, tagConfig)
    io.upstream <> cache.io.upstream
    io.downstream <> cache.io.downstream
    io.tl <> cache.io.tl
    cache.io.flushRequest := io.flushRequest
    io.flushDone := cache.io.flushDone
    io.hit := cache.io.hit
    io.miss := cache.io.miss
    io.mshrOccupancy := (cache match {
        case concurrent: NonBlockingCoherentLineCache => BoringUtils.bore(concurrent.mshrOccupancy)
        case _ => 0.U
    })
}

object CoherentReadMshrGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CoherentReadMshrGsim(args(1).toInt,
        args.lift(2).map(_.toInt).getOrElse(512), args.lift(3).map(_.toInt).getOrElse(2),
        args.lift(4).map(_.toInt).getOrElse(8),
        CacheTagConfig(compact = args.lift(5).contains("1")),
        args.lift(6).map(BigInt(_)).getOrElse(BigInt("80010000", 16))), Array("--target-dir", args.head))
}
