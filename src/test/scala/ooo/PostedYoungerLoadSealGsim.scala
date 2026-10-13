package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Real production combinational guard with independently authored raw instructions.
  * This component does not prove the backend's staged-token/ROB live-window source.
  */
class PostedYoungerLoadSealGsim extends Module {
    val io = IO(new Bundle {
        val enabled = Input(Bool())
        val postedBusy = Input(Bool())
        val headValid = Input(Bool())
        val choiceValid = Input(Bool())
        val younger = Input(Bool())
        val live = Input(Bool())
        val pending = Input(Bool())
        val indexMatches = Input(Bool())
        val physical = Input(Bool())
        val ordinaryRam = Input(Bool())
        val pmpAllowed = Input(Bool())
        val aligned = Input(Bool())
        val selectedInstruction = Input(UInt(32.W))
        val headInstruction = Input(UInt(32.W))
        val selectedFetchFault = Input(Bool())
        val selectedFetchPageFault = Input(Bool())
        val headFetchFault = Input(Bool())
        val headFetchPageFault = Input(Bool())
        val hardCauses = Input(UInt(8.W))
        val postedEligible = Input(Bool())
        val preparedPhysicalStore = Input(Bool())
        val deferred = Output(Bool())
        val seal = Output(Bool())
    })
    val selectedDecode = Module(new IntegerDecode(enableSystem = true, enableAtomic = true))
    val headDecode = Module(new IntegerDecode(enableSystem = true, enableAtomic = true))
    selectedDecode.io.instruction := io.selectedInstruction
    selectedDecode.io.pc := 0.U
    headDecode.io.instruction := io.headInstruction
    headDecode.io.pc := 0.U
    val selected = WireDefault(selectedDecode.io.decoded)
    selected.fetchFault := io.selectedFetchFault
    selected.fetchPageFault := io.selectedFetchPageFault
    val head = WireDefault(headDecode.io.decoded)
    head.fetchFault := io.headFetchFault
    head.fetchPageFault := io.headFetchPageFault
    io.deferred := io.enabled && PostedYoungerLoadSeal.defer(io.postedBusy, io.headValid, head,
        io.choiceValid, io.younger, io.live, io.pending, io.indexMatches, selected,
        io.physical, io.ordinaryRam, io.pmpAllowed, io.aligned)
    io.seal := io.hardCauses.orR || (io.headValid && head.system) ||
        (io.choiceValid && !io.postedEligible && !io.preparedPhysicalStore && !io.deferred)
}

object PostedYoungerLoadSealGsimMain extends App {
    require(args.length == 1, "one fresh component output directory required")
    ChiselStage.emitCHIRRTLFile(new PostedYoungerLoadSealGsim, Array("--target-dir", args(0)))
}
