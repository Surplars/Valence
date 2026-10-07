package soc.core.ooo

import chisel3._
import chisel3.util._

/** One combinational capture decision/cycle, no storage or extra redirect cycle.
  * Decide priority from ORIGINAL resolution flags, then qualify that winner.
  * A killed older winner must not fall back to a younger live branch.
  * Slot decoding and kill qualification depend on early issue indices, not
  * the late branch result / prediction mismatch or a selected payload mux.
  */
class EarlyRedirectCapture(p: OooParams, oldestHighLane: Boolean) extends Module {
    val io = IO(new Bundle {
        val flags = Input(UInt(p.completionWidth.W))
        val indices = Input(Vec(p.completionWidth, UInt(p.robBits.W)))
        val killed = Input(UInt(p.robEntries.W))
        val blocked = Input(Bool())
        val selected = Output(UInt(p.completionWidth.W))
        val accept = Output(Bool())
        val clear = Output(UInt(p.robEntries.W))
    })
    val ordered = if (oldestHighLane) Reverse(io.flags) else io.flags
    val winner = PriorityEncoderOH(ordered)
    io.selected := (if (oldestHighLane) Reverse(winner) else winner)
    val slots = (0 until p.completionWidth).map { lane =>
        VecInit((0 until p.robEntries).map(slot => io.indices(lane) === slot.U)).asUInt
    }
    val qualified = (0 until p.completionWidth).map { lane =>
        !io.blocked && !(slots(lane) & io.killed).orR
    }
    val grants = VecInit((0 until p.completionWidth).map(lane =>
        io.selected(lane) && qualified(lane)))
    io.accept := grants.asUInt.orR
    io.clear := VecInit((0 until p.robEntries).map { slot =>
        (0 until p.completionWidth).map(lane => grants(lane) && slots(lane)(slot)).reduce(_ || _)
    }).asUInt
}
