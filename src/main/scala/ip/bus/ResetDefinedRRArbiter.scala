package soc.ip.bus

import chisel3._
import chisel3.util._

/** Round-robin selection with an explicit cold-reset priority.
  *
  * The first simultaneous offer prefers input zero. Thereafter selection starts
  * immediately after the last accepted input and wraps, as in RRArbiter. VALID,
  * payload, chosen and every READY use the same selection, so first nonzero
  * offers cannot be accepted at only one side in four-state simulation.
  *
  * No payload register, credit, lock or extra cycle is introduced. In particular
  * an unaccepted offer may still be withdrawn by a cancelling internal producer;
  * this helper does not upgrade Decoupled to an irrevocable interface.
  */
class ResetDefinedRRArbiter[T <: Data](gen: T, n: Int) extends Module {
    require(n >= 1)
    val io = IO(new ArbiterIO(gen, n))
    if (n == 1) {
        io.out <> io.in(0)
        io.chosen := 0.U
    } else {
        val last = RegInit((n - 1).U(log2Ceil(n).W))
        val offered = VecInit(io.in.map(_.valid)).asUInt
        val after = VecInit((0 until n).map(i => io.in(i).valid && i.U > last)).asUInt
        val selected = Mux(after.orR, PriorityEncoder(after), PriorityEncoder(offered))
        io.chosen := selected
        io.out.valid := io.in(selected).valid
        io.out.bits := io.in(selected).bits
        for (i <- 0 until n) io.in(i).ready := io.out.ready && selected === i.U
        when(io.out.fire) { last := selected }
        assert(PopCount(VecInit(io.in.map(_.fire))) === io.out.fire.asUInt,
            "reset-defined arbitration input/output acceptance differs")
    }
}
