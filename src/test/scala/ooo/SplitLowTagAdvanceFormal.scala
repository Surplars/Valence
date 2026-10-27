package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo.SplitLowTagAdvance

/** Arithmetic and conditional-state projection, NOT a RenameRob substitute.
  * Predecessor state is an unconstrained input: full64 exhaustion boundaries need
  * no production state-injection port and no narrowed generation counter.
  */
class SplitLowTagAdvanceFormal(mutation: String = "none") extends RawModule {
    require(Set("none", "carry", "exhaustion").contains(mutation))
    val base = IO(Input(UInt(64.W)))
    val count = IO(Input(UInt(2.W)))
    val exhausted = IO(Input(Bool()))
    val resetState = IO(Input(Bool()))
    val recovery = IO(Input(Bool()))
    val advanced = IO(Output(UInt(65.W)))
    val original = IO(Output(UInt(65.W)))
    val lane0 = IO(Output(UInt(64.W)))
    val lane1 = IO(Output(UInt(65.W)))
    val nextTag = IO(Output(UInt(64.W)))
    val nextExhausted = IO(Output(Bool()))
    val actual = SplitLowTagAdvance(base, count)
    val selected = if (mutation == "carry") {
        // Deliberately incorrect low carry selector, confined to a negative fixture.
        val low = base(1, 0) +& count
        Cat(Mux(low(1), base(63, 2) +& 1.U, Cat(0.U(1.W), base(63, 2))), low(1, 0))
    } else actual
    advanced := selected
    original := base +& count
    lane0 := base
    lane1 := base +& 1.U
    val update = !recovery && count =/= 0.U
    nextTag := Mux(resetState, 0.U, Mux(update, selected(63, 0), base))
    nextExhausted := Mux(resetState, false.B,
        Mux(update, selected(64), if (mutation == "exhaustion") false.B else exhausted))
}

object SplitLowTagAdvanceFormalMain extends App {
    require(args.length == 2)
    ChiselStage.emitCHIRRTLFile(new SplitLowTagAdvanceFormal(args(1)), Array("--target-dir", args(0)))
}
