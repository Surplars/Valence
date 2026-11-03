package soc.core.inorder

import chisel3._
import chisel3.util._

/** One bank's exact logical validity, with a registered clear guard.
  * Invalidate is visible immediately AFTER its edge, wins over that edge's
  * allocation, and does not delay the following cycle's training acceptance.
  * Raw bits have no reset/CE: they clear locally one edge later while hidden.
  * Capacity is rows, training II=1, no queue/backpressure or CPU stage added.
  */
class I1BranchBankValid(rows: Int) extends Module {
    require(rows >= 2 && isPow2(rows))
    val io = IO(new Bundle {
        val lookupRow = Input(UInt(log2Ceil(rows).W))
        val trainingRow = Input(UInt(log2Ceil(rows).W))
        val allocate = Input(Bool())
        val remove = Input(Bool())
        val invalidate = Input(Bool())
        val lookupValid = Output(Bool())
        val trainingValid = Output(Bool())
    })
    val clearing = RegInit(true.B)
    // Explicit reset dependence also refreshes the pinned event simulator's
    // NEXT value on reset release; this is equivalent to the register reset.
    clearing := io.invalidate || reset.asBool
    val raw = Reg(UInt(rows.W))
    val selected = UIntToOH(io.trainingRow, rows)
    val set = selected & Fill(rows, io.allocate)
    val remove = selected & Fill(rows, io.remove)
    raw := ((raw & Fill(rows, !clearing)) & ~remove) | set
    io.lookupValid := !clearing && raw(io.lookupRow)
    io.trainingValid := !clearing && raw(io.trainingRow)
}
