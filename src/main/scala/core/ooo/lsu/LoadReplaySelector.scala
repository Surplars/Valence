package soc.core.ooo

import chisel3._
import chisel3.util._

/** Combinational, one decision/cycle, no extra replay or retirement stage.
  * Select the oldest overlapping younger load in circular ROB order. Keep the
  * winner one-hot so PC/token selection need not decode a tournament's index.
  */
class LoadReplaySelector(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val checkedValid = Input(Bool())
        val checkedIndex = Input(UInt(p.robBits.W))
        val checkedBeat = Input(UInt(61.W))
        val checkedLanes = Input(UInt(8.W))
        val eligible = Input(UInt(p.robEntries.W))
        val beats = Input(Vec(p.robEntries, UInt(61.W)))
        val lanes = Input(Vec(p.robEntries, UInt(8.W)))
        val valid = Output(Bool())
        val index = Output(UInt(p.robBits.W))
        val oneHot = Output(UInt(p.robEntries.W))
    })
    val checkedAge = io.checkedIndex - io.head
    val hits = VecInit((0 until p.robEntries).map { i =>
        // Explicit short comparisons avoid a single wide equality expression
        // feeding the winner/target chain. Compare ALL 61 bits, including high PA.
        val beatMatches = VecInit((0 until 61 by 6).map { low =>
            val high = math.min(low + 5, 60)
            io.beats(i)(high, low) === io.checkedBeat(high, low)
        }).asUInt.andR
        val age = i.U(p.robBits.W) - io.head
        io.checkedValid && io.eligible(i) && age > checkedAge && beatMatches &&
            (io.lanes(i) & io.checkedLanes).orR
    }).asUInt
    // Lowest physical slot >= head wins; wrap to slots < head only if needed.
    // This is circular age order, not a fixed physical-slot priority.
    val afterHead = hits & VecInit((0 until p.robEntries).map(i => i.U >= io.head)).asUInt
    io.oneHot := PriorityEncoderOH(Mux(afterHead.orR, afterHead, hits))
    io.valid := hits.orR
    io.index := OHToUInt(io.oneHot)
}
