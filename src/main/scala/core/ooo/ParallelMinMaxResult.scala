package soc.core.ooo

import chisel3._
import chisel3.util._

/** MIN/MAX result with W payload prepared before late full64 comparison.
  * Capacity/latency 0, II 1. W controls change data only, never comparison width;
  * even illegal-W numerical results match the original ALU contract.
  */
class ParallelMinMaxResult extends Module {
    val io = IO(new Bundle {
        val operation = Input(UInt(6.W))
        val word = Input(Bool())
        val left = Input(UInt(64.W))
        val right = Input(UInt(64.W))
        val result = Output(UInt(64.W))
    })
    val op = io.operation
    val signedLess = io.left.asSInt < io.right.asSInt
    val unsignedLess = io.left < io.right
    val left = Mux(io.word, Cat(Fill(32, io.left(31)), io.left(31, 0)), io.left)
    val right = Mux(io.word, Cat(Fill(32, io.right(31)), io.right(31, 0)), io.right)
    val chooseLeft = (op === IntegerOp.min && signedLess) || (op === IntegerOp.max && !signedLess) ||
        (op === IntegerOp.minU && unsignedLess) || (op === IntegerOp.maxU && !unsignedLess)
    val chooseRight = (op === IntegerOp.min && !signedLess) || (op === IntegerOp.max && signedLess) ||
        (op === IntegerOp.minU && !unsignedLess) || (op === IntegerOp.maxU && unsignedLess)
    io.result := Mux1H(Seq(chooseLeft -> left, chooseRight -> right))
}
