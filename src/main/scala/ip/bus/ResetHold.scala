package soc.ip.bus

import chisel3._
import chisel3.util._

/** Common reset asserts asynchronously when instantiated with AsyncReset.
  * Release is a single registered output after exactly cycles local edges;
  * never derive an asynchronous reset from a combinational counter decode.
  */
class ResetHold(cycles: Int) extends Module {
    require(cycles >= 1)
    val io = IO(new Bundle { val asserted = Output(Bool()) })
    val remaining = RegInit(cycles.U(log2Ceil(cycles + 1).max(1).W))
    val held = RegInit(true.B)
    when(remaining =/= 0.U) { remaining := remaining - 1.U }
    when(remaining === 1.U) { held := false.B }
    io.asserted := held
}
