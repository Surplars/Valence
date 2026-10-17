package soc.core.inorder

import chisel3._
import chisel3.util._

/** I1-local variant of soc.ip.bus.TwoEntryRegisterQueue; shared IP is unchanged.
  * Same two slots, registered output, occupancy-only credit and no full credit
  * borrowing. Optional preparation changes ONLY unowned payload registers.
  */
class I1PreparedRegisterQueue[T <: Data](gen: T, preparePayload: Boolean = false) extends Module {
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
    if (preparePayload) {
        // Moving an owned tail always wins. Otherwise head/tail prepare only
        // when empty (or actually vacated), regardless of incoming VALID.
        // A held owned head and a full tail cannot change.
        when(pop && tailValid) { head := tail }
        when(!headValid || (pop && !tailValid)) { head := io.enq.bits }
        when(!tailValid && headValid && !pop) { tail := io.enq.bits }
    }
    when(pop) {
        headValid := tailValid
        if (!preparePayload) when(tailValid) { head := tail }
        tailValid := false.B
    }
    when(push) {
        when(!headValid || (pop && !tailValid)) {
            if (!preparePayload) { head := io.enq.bits }
            headValid := true.B
        }.otherwise {
            if (!preparePayload) { tail := io.enq.bits }
            tailValid := true.B
        }
    }
    assert(!tailValid || headValid, "prepared register queue tail has no head owner")
}
