package ooo

import chisel3._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo._

/** Independent old/new peers. The host owns requests, expected addresses,
  * response words and errors; observations below are coverage only.
  */
class FetchAddressLineCacheGsim(prefetch: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort(2))
        val responseLow = Output(UInt(64.W))
        val responseHigh = Output(UInt(64.W))
        val tl = new TLBundle(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3))
        val invalidate = Input(Bool())
        val pmpCfg0 = Input(UInt(8.W))
        val pmpAddr0 = Input(UInt(54.W))
        val privilege = Input(UInt(2.W))
        val observedState = Output(UInt(3.W))
        val routeLocked = Output(Bool())
        val routeFallback = Output(Bool())
    })
    val cache = Module(new InstructionLineCache(lines = 16, packetWords = 2,
        prefetchEnabled = prefetch, parallelFallbackAddresses = true))
    val previousCache = Module(new FrozenInstructionLineCacheBeforePaD(lines = 16, packetWords = 2,
        prefetchEnabled = prefetch, parallelFallbackAddresses = true))
    io.fetch <> cache.io.fetch
    io.tl <> cache.io.tl
    io.responseLow := cache.io.fetch.response.bits
    io.responseHigh := 0.U
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg0
    pmp.addr(0) := io.pmpAddr0
    PmpState.decodeRegions(pmp)
    cache.io.pmpState := pmp
    cache.io.privilege := io.privilege
    cache.io.invalidate := io.invalidate
    previousCache.io.fetch.request.valid := io.fetch.request.valid
    previousCache.io.fetch.request.bits := io.fetch.request.bits
    previousCache.io.fetch.requestMask := io.fetch.requestMask
    previousCache.io.fetch.response.ready := io.fetch.response.ready
    previousCache.io.pmpState := pmp
    previousCache.io.privilege := io.privilege
    previousCache.io.invalidate := io.invalidate
    previousCache.io.tl.a.ready := io.tl.a.ready
    previousCache.io.tl.b.valid := io.tl.b.valid
    previousCache.io.tl.b.bits := io.tl.b.bits
    previousCache.io.tl.c.ready := io.tl.c.ready
    previousCache.io.tl.d.valid := io.tl.d.valid
    previousCache.io.tl.d.bits := io.tl.d.bits
    previousCache.io.tl.e.ready := io.tl.e.ready
    assert(cache.io.fetch.request.ready === previousCache.io.fetch.request.ready &&
        cache.io.fetch.response.valid === previousCache.io.fetch.response.valid &&
        cache.io.tl.a.valid === previousCache.io.tl.a.valid &&
        cache.io.tl.d.ready === previousCache.io.tl.d.ready && cache.io.idle === previousCache.io.idle,
        "fetch address cache peer handshake mismatch")
    when(cache.io.tl.a.valid) {
        assert(cache.io.tl.a.bits.asUInt === previousCache.io.tl.a.bits.asUInt,
            "fetch address cache peer valid A payload mismatch")
    }
    when(cache.io.fetch.response.valid) {
        assert(cache.io.fetch.response.bits === previousCache.io.fetch.response.bits &&
            cache.io.fetch.responseError === previousCache.io.fetch.responseError &&
            cache.io.fetch.responsePageFault === previousCache.io.fetch.responsePageFault,
            "fetch address cache peer response mismatch")
    }
    io.observedState := BoringUtils.bore(cache.perfState)
    io.routeLocked := BoringUtils.bore(cache.lockedA)
    io.routeFallback := BoringUtils.bore(cache.chooseFallback)
}
object FetchAddressLineCacheGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchAddressLineCacheGsim(args.drop(1).contains("prefetch")),
        Array("--target-dir", args.head))
}
