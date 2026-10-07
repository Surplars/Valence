package soc.ip.bus

import chisel3._
import chisel3.util._

/** Two registered elastic slots, no empty bypass or full-queue credit borrowing.
  * Capacity 2, minimum latency 1, II=1. The consumer always reads a dedicated
  * head register: there is no pointer-indexed LUTRAM or payload read mux.
  * Reset cancels both slots. Ready depends only on local occupancy.
  */
class TwoEntryRegisterQueue[T <: Data](gen: T) extends Module {
    val io = IO(new QueueIO(gen, 2))
    val head = Reg(gen.cloneType)
    val tail = Reg(gen.cloneType)
    val headValid = RegInit(false.B)
    val tailValid = RegInit(false.B)
    io.enq.ready := !tailValid
    io.deq.valid := headValid
    io.deq.bits := head
    io.count := headValid.asUInt +& tailValid.asUInt
    val push = io.enq.fire
    val pop = io.deq.fire
    when(pop) {
        headValid := tailValid
        when(tailValid) { head := tail }
        tailValid := false.B
    }
    when(push) {
        when(!headValid || (pop && !tailValid)) {
            head := io.enq.bits
            headValid := true.B
        }.otherwise {
            tail := io.enq.bits
            tailValid := true.B
        }
    }
    assert(!tailValid || headValid, "register queue tail cannot exist without its head")
}
