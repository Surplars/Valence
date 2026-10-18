package soc.core.inorder

import chisel3._
import chisel3.util._

/** Same non-flow/non-pipe FIFO contract and storage as Queue(UInt, entries).
  * Only an unowned RAM row may prepare data without VALID. Pointer/count
  * commits still require a real handshake. A full FIFO cannot overwrite its
  * head, even on a simultaneous dequeue; no borrowed credits or new slots.
  */
class I1PreparedMetadataQueue(width: Int, entries: Int) extends Module {
    require(width >= 1 && entries >= 2 && isPow2(entries))
    val io = IO(new QueueIO(UInt(width.W), entries))
    val ram = Mem(entries, UInt(width.W))
    val enqPtr = RegInit(0.U(log2Ceil(entries).W))
    val deqPtr = RegInit(0.U(log2Ceil(entries).W))
    val maybeFull = RegInit(false.B)
    val equal = enqPtr === deqPtr
    val full = equal && maybeFull
    val empty = equal && !maybeFull
    io.enq.ready := !full
    io.deq.valid := !empty
    io.deq.bits := ram.read(deqPtr)
    io.count := Mux(equal, Mux(maybeFull, entries.U, 0.U), (enqPtr - deqPtr).asUInt)
    // enqPtr names free storage whenever !full. Stored payload remains
    // architecturally invisible until enq.fire advances the existing owner.
    when(!full) { ram.write(enqPtr, io.enq.bits) }
    when(io.enq.fire) { enqPtr := enqPtr + 1.U }
    when(io.deq.fire) { deqPtr := deqPtr + 1.U }
    when(io.enq.fire =/= io.deq.fire) { maybeFull := io.enq.fire }
}
