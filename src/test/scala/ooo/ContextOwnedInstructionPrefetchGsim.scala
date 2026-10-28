package ooo

import chisel3._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo._

/** Direct cache-contract fixture. The independent host owns request certificates,
  * PMP programming, cancellation, TL service/backpressure and the demand oracle.
  * No service latency or error expectation is generated from the DUT.
  */
class ContextOwnedInstructionPrefetchGsim(bankedData: Boolean = false) extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort(2, withRequestContext = true, withSpeculationContext = true))
        val tl = new TLBundle(params)
        // Explicit scalar ABI: GSIM cannot emit scalar setters for top-level Vec inputs.
        val pmpCfg_0 = Input(UInt(8.W))
        val pmpCfg_1 = Input(UInt(8.W))
        val pmpCfg_2 = Input(UInt(8.W))
        val pmpCfg_3 = Input(UInt(8.W))
        val pmpCfg_4 = Input(UInt(8.W))
        val pmpCfg_5 = Input(UInt(8.W))
        val pmpCfg_6 = Input(UInt(8.W))
        val pmpCfg_7 = Input(UInt(8.W))
        val pmpCfg_8 = Input(UInt(8.W))
        val pmpCfg_9 = Input(UInt(8.W))
        val pmpCfg_10 = Input(UInt(8.W))
        val pmpCfg_11 = Input(UInt(8.W))
        val pmpCfg_12 = Input(UInt(8.W))
        val pmpCfg_13 = Input(UInt(8.W))
        val pmpCfg_14 = Input(UInt(8.W))
        val pmpCfg_15 = Input(UInt(8.W))
        val pmpAddr_0 = Input(UInt(54.W))
        val pmpAddr_1 = Input(UInt(54.W))
        val pmpAddr_2 = Input(UInt(54.W))
        val pmpAddr_3 = Input(UInt(54.W))
        val pmpAddr_4 = Input(UInt(54.W))
        val pmpAddr_5 = Input(UInt(54.W))
        val pmpAddr_6 = Input(UInt(54.W))
        val pmpAddr_7 = Input(UInt(54.W))
        val pmpAddr_8 = Input(UInt(54.W))
        val pmpAddr_9 = Input(UInt(54.W))
        val pmpAddr_10 = Input(UInt(54.W))
        val pmpAddr_11 = Input(UInt(54.W))
        val pmpAddr_12 = Input(UInt(54.W))
        val pmpAddr_13 = Input(UInt(54.W))
        val pmpAddr_14 = Input(UInt(54.W))
        val pmpAddr_15 = Input(UInt(54.W))
        val livePrivilege = Input(UInt(2.W))
        val invalidate = Input(Bool())
        val kill = Input(Bool())
        val minimumSequence = Input(UInt(64.W))
        val ageUsable = Input(Bool())
        val idle = Output(Bool())
        val state = Output(UInt(3.W))
        val speculativeRequest = Output(Bool())
        val speculativeComplete = Output(Bool())
        val speculativeError = Output(Bool())
        val speculativeInstall = Output(Bool())
        val speculativeStaleDrop = Output(Bool())
        val joinedDemand = Output(Bool())
    })
    private val base = BigInt("80010000", 16)
    private val bytes = BigInt(8192)
    val cache = Module(new InstructionLineCache(params, ramBase = base, ramBytes = bytes,
        lines = 16, prefetchEnabled = false, bankedData = bankedData, withRequestContext = true,
        contextOwnedInstructionPrefetch = true,
        sideEffectFreeFetchRanges = Seq(SideEffectFreeFetchRange(base, bytes))))
    cache.io.fetch <> io.fetch
    io.tl <> cache.io.tl
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg := VecInit(Seq(
        io.pmpCfg_0, io.pmpCfg_1, io.pmpCfg_2, io.pmpCfg_3,
        io.pmpCfg_4, io.pmpCfg_5, io.pmpCfg_6, io.pmpCfg_7,
        io.pmpCfg_8, io.pmpCfg_9, io.pmpCfg_10, io.pmpCfg_11,
        io.pmpCfg_12, io.pmpCfg_13, io.pmpCfg_14, io.pmpCfg_15))
    pmp.addr := VecInit(Seq(
        io.pmpAddr_0, io.pmpAddr_1, io.pmpAddr_2, io.pmpAddr_3,
        io.pmpAddr_4, io.pmpAddr_5, io.pmpAddr_6, io.pmpAddr_7,
        io.pmpAddr_8, io.pmpAddr_9, io.pmpAddr_10, io.pmpAddr_11,
        io.pmpAddr_12, io.pmpAddr_13, io.pmpAddr_14, io.pmpAddr_15))
    PmpState.decodeRegions(pmp)
    cache.io.pmpState := pmp
    cache.io.privilege := io.livePrivilege
    cache.io.invalidate := io.invalidate
    cache.io.speculationKill.get := io.kill
    cache.io.speculationMinimumSequence.get := io.minimumSequence
    cache.io.speculationAgeUsable.get := io.ageUsable
    io.idle := cache.io.idle
    // These are already-generated child Data, not parent-scope expressions.
    // Bore each observation individually; no normal production port is added.
    io.state := BoringUtils.bore(cache.perfState)
    io.speculativeRequest := BoringUtils.bore(cache.perfContextPrefetchRequest)
    io.speculativeComplete := BoringUtils.bore(cache.perfContextPrefetchComplete)
    io.speculativeError := BoringUtils.bore(cache.perfContextPrefetchError)
    io.speculativeInstall := BoringUtils.bore(cache.perfContextPrefetchInstall)
    io.speculativeStaleDrop := BoringUtils.bore(cache.perfContextPrefetchStaleDrop)
    io.joinedDemand := BoringUtils.bore(cache.perfContextPrefetchJoin)
}

object ContextOwnedInstructionPrefetchGsimMain extends App {
    require(args.nonEmpty, "usage: output-dir [--banked-instruction-data]")
    ChiselStage.emitCHIRRTLFile(new ContextOwnedInstructionPrefetchGsim(
        bankedData = args.contains("--banked-instruction-data")), Array("--target-dir", args.head))
}
