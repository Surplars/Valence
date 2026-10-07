package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLBundle
import soc.core.ooo.{InstructionLineCache, InstructionPort, PmpState}

class InstructionLineCacheGsim(prefetchEnabled: Boolean = false, packetWords: Int = 2,
    parallelAddresses: Boolean = false, lines: Int = 16) extends Module {
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort(packetWords))
        val responseLow = Output(UInt(64.W))
        val responseHigh = Output(UInt(64.W))
        val tl = new TLBundle(soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3))
        val invalidate = Input(Bool())
        val pmpCfg0 = Input(UInt(8.W))
        val pmpAddr0 = Input(UInt(54.W))
        val privilege = Input(UInt(2.W))
    })
    // Four conflicting lines must fit even at the largest accepted geometry.
    private val testRamBytes = math.max(4096, 4 * 64 * (lines / 2))
    val cache = Module(new InstructionLineCache(lines = lines, ramBytes = testRamBytes,
        prefetchEnabled = prefetchEnabled, packetWords = packetWords, parallelFallbackAddresses = parallelAddresses))
    io.fetch <> cache.io.fetch
    io.responseLow := cache.io.fetch.response.bits(63, 0)
    io.responseHigh := (if (packetWords == 4) cache.io.fetch.response.bits(127, 64) else 0.U)
    io.tl <> cache.io.tl
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg0
    pmp.addr(0) := io.pmpAddr0
    PmpState.decodeRegions(pmp)
    cache.io.pmpState := pmp
    cache.io.privilege := io.privilege
    cache.io.invalidate := io.invalidate
}

object InstructionLineCacheGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new InstructionLineCacheGsim(args.lift(1).contains("prefetch"),
        args.lift(2).map(_.toInt).getOrElse(2), args.drop(1).contains("parallel-addresses"),
        args.drop(1).find(_.startsWith("lines=")).map(_.stripPrefix("lines=").toInt).getOrElse(16)),
        Array("--target-dir", args.head))
}
