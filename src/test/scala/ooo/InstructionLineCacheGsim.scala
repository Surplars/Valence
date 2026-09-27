package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLBundle
import soc.core.ooo.{InstructionLineCache, InstructionPort, PmpState}

class InstructionLineCacheGsim(prefetchEnabled: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort)
        val tl = new TLBundle(soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3))
        val invalidate = Input(Bool())
        val pmpCfg0 = Input(UInt(8.W))
        val pmpAddr0 = Input(UInt(54.W))
        val privilege = Input(UInt(2.W))
    })
    val cache = Module(new InstructionLineCache(prefetchEnabled = prefetchEnabled))
    io.fetch <> cache.io.fetch
    io.tl <> cache.io.tl
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg0
    pmp.addr(0) := io.pmpAddr0
    cache.io.pmpState := pmp
    cache.io.privilege := io.privilege
    cache.io.invalidate := io.invalidate
}

object InstructionLineCacheGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new InstructionLineCacheGsim(args.lift(1).contains("prefetch")),
        Array("--target-dir", args.head))
}
