package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Real two-slot translation/permission/ordered-return boundary. The host
  * independently supplies TLB and physical results, including faults and stalls.
  * No cache is hidden here: source identity, held offers and cutoff are observable.
  */
class ContextOwnedInstructionTranslationGsim extends Module {
    private val p = FpgaNextConfig.Selected.coreParams.copy(alignedFetchSinglePage = true)
    val io = IO(new Bundle {
        val virtual = Flipped(new InstructionPort)
        val physical = new InstructionPort(2, withRequestContext = true, withSpeculationContext = true)
        val translation = new SvTranslationPort
        val vmState = Input(new VmCsrState)
        val privilege = Input(UInt(2.W))
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
        val kill = Input(Bool())
        // Host confirms any external standalone speculative/cache obligations drained.
        val externalDrained = Input(Bool())
        val idle = Output(Bool())
        val minimumSequence = Output(UInt(64.W))
        val ageUsable = Output(Bool())
    })
    val adapter = Module(new InstructionTranslationAdapter(p, transactionSlots = 2,
        withRequestContext = true, contextOwnedInstructionPrefetch = true))
    adapter.io.virtual <> io.virtual
    io.physical <> adapter.io.physical
    io.translation <> adapter.io.translation
    adapter.io.vmState := io.vmState
    adapter.io.privilege := io.privilege
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
    adapter.io.pmpState := pmp
    adapter.io.speculationKill.get := io.kill
    adapter.io.speculationDrained.get := io.externalDrained && adapter.io.idle && !io.virtual.request.valid
    io.idle := adapter.io.idle
    io.minimumSequence := adapter.io.speculationMinimumSequence.get
    io.ageUsable := adapter.io.speculationAgeUsable.get
}

object ContextOwnedInstructionTranslationGsimMain extends App {
    require(args.length == 1, "usage: output-dir")
    ChiselStage.emitCHIRRTLFile(new ContextOwnedInstructionTranslationGsim, Array("--target-dir", args.head))
}
