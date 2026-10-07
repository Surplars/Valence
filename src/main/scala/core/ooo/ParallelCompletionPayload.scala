package soc.core.ooo

import chisel3._
import chisel3.util._

/** Stateless completion payload selection. Sources in decreasing legacy priority:
  * LSU, divider, multiplier, system, held branch; otherwise current ALU lane.
  * Raw presence chooses payload even when downstream authorization rejects it.
  * This does not grant a completion or bypass any full-token ownership check.
  * No added cycle/capacity; one selected payload per cycle under arbitrary overlap.
  */
class ParallelCompletionPayload(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val present = Input(UInt(5.W))
        val candidates = Input(Vec(5, new BackendCompletion(p)))
        val fallback = Input(new BackendCompletion(p))
        val selected = Output(new BackendCompletion(p))
        val grants = Output(UInt(6.W))
    })
    val selected = VecInit((0 until 5).map { i =>
        io.present(i) && (if (i == 0) true.B else !io.present(i - 1, 0).orR)
    } :+ !io.present.orR).asUInt
    io.grants := selected
    io.selected := CircularIssueSelector.selectPayload(selected,
        io.candidates.map(_.asUInt).toSeq :+ io.fallback.asUInt).asTypeOf(new BackendCompletion(p))
    assert(PopCount(selected) === 1.U, "completion payload must select exactly one legacy-priority source")
}
