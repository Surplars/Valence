package soc.core.ooo

import chisel3._
import chisel3.util._

/** A redundant age boundary captured on the SAME edge as ROB head advancement.
  * Recovery removes tails, so accepted commits are the only head movement.
  * No issue delay: output describes the current head, not last cycle's head.
  */
class RegisteredRobHeadMask(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val commits = Input(UInt(log2Ceil(p.commitWidth + 1).W))
        val afterHead = Output(UInt(p.robEntries.W))
    })
    val mask = RegInit(((BigInt(1) << p.robEntries) - 1).U(p.robEntries.W))
    val candidates = (0 to p.commitWidth).map { count =>
        val nextHead = (io.head + count.U)(p.robBits - 1, 0)
        val nextMask = if (count == 0) mask
            else VecInit((0 until p.robEntries).map(slot => slot.U >= nextHead)).asUInt
        (io.commits === count.U) -> nextMask
    }
    mask := Mux1H(candidates)
    io.afterHead := mask
    assert(io.commits <= p.commitWidth.U, "ROB head movement must count accepted commits")
    assert(mask === VecInit((0 until p.robEntries).map(slot => slot.U >= io.head)).asUInt,
        "registered age boundary must track current ROB head including wrap")
}
