package soc.core.ooo

import chisel3._
import chisel3.util._

object ControlFlow {
    val none = 0.U(4.W)
    val beq  = 1.U(4.W)
    val bne  = 2.U(4.W)
    val blt  = 3.U(4.W)
    val bge  = 4.U(4.W)
    val bltu = 5.U(4.W)
    val bgeu = 6.U(4.W)
    val jal  = 7.U(4.W)
    val jalr = 8.U(4.W)
}

/** One combinational branch/jump result per lane per cycle. A not-taken
  * conditional branch never faults on its unused target; JALR clears bit zero before checking alignment.
  */
class BranchUnit(ialign16: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val kind       = Input(UInt(4.W))
        val pc         = Input(UInt(64.W))
        val shortInstruction = Input(Bool())
        val immediate  = Input(UInt(64.W))
        val left       = Input(UInt(64.W))
        val right      = Input(UInt(64.W))
        val nextPc     = Output(UInt(64.W))
        val target     = Output(UInt(64.W))
        val data       = Output(UInt(64.W))
        val misaligned = Output(Bool())
        val legal      = Output(Bool())
    })
    val jump  = io.kind === ControlFlow.jal || io.kind === ControlFlow.jalr
    val taken = jump || MuxLookup(io.kind, false.B)(
        Seq(
            ControlFlow.beq  -> (io.left === io.right),
            ControlFlow.bne  -> (io.left =/= io.right),
            ControlFlow.blt  -> (io.left.asSInt < io.right.asSInt),
            ControlFlow.bge  -> (io.left.asSInt >= io.right.asSInt),
            ControlFlow.bltu -> (io.left < io.right),
            ControlFlow.bgeu -> (io.left >= io.right)
        )
    )
    val sum = Mux(io.kind === ControlFlow.jalr, io.left, io.pc) + io.immediate
    io.target     := Mux(io.kind === ControlFlow.jalr, Cat(sum(63, 1), 0.U(1.W)), sum)
    val sequential = io.pc + Mux(io.shortInstruction, 2.U, 4.U)
    io.nextPc     := Mux(taken, io.target, sequential)
    io.data       := Mux(jump, sequential, 0.U)
    io.misaligned := taken && (if (ialign16) io.target(0) else io.target(1, 0).orR)
    io.legal      := io.kind >= ControlFlow.beq && io.kind <= ControlFlow.jalr
}
