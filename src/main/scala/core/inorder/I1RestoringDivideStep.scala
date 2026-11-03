package soc.core.inorder

import chisel3._
import chisel3.util._

/** Pure unsigned restoring step: capacity/state 0, combinational latency, no ready/valid.
  * All XLEN+1-bit windows and XLEN-bit divisors (including zero) are defined.
  * The extended difference's borrow selects the original window or exact remainder.
  */
class I1RestoringDivideStep(xlen: Int) extends Module {
    require(Set(32, 64).contains(xlen))
    val io = IO(new Bundle {
        val window = Input(UInt((xlen + 1).W))
        val divisor = Input(UInt(xlen.W))
        val quotientBit = Output(Bool())
        val remainder = Output(UInt((xlen + 1).W))
    })
    val difference = Cat(0.U(1.W), io.window) - Cat(0.U(2.W), io.divisor)
    io.quotientBit := !difference(xlen + 1)
    io.remainder := Mux(io.quotientBit, difference(xlen, 0), io.window)
}
