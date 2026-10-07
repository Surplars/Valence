package soc.core.ooo

import chisel3._
import chisel3.util._

/** Four stateless prediction sources: known indirect, return, indirect table,
  * PC-relative. Presence chooses the original priority before qualification:
  * an ineligible winning source must not fall back to a lower-priority source.
  * Alignment/successor comparisons run on independent target sources, not on
  * an opcode-selected full64 target. Capacity 0, latency 0, one result/cycle.
  */
class PredictionSourceQualification extends Module {
    val io = IO(new Bundle {
        val present = Input(UInt(4.W))
        val aligned = Input(UInt(4.W))
        val different = Input(UInt(4.W))
        val grants = Output(UInt(4.W))
        val predicts = Output(Bool())
    })
    val grants = VecInit((0 until 4).map { i =>
        io.present(i) && !(0 until i).map(io.present(_)).foldLeft(false.B)(_ || _)
    })
    io.grants := grants.asUInt
    io.predicts := (grants.asUInt & io.aligned & io.different).orR
}
