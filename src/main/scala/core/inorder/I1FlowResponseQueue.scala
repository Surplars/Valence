package soc.core.inorder

import chisel3._
import chisel3.util._

/** Exactly Queue(pipe=false, flow=true), exposing its two payload sources so
  * the client can fuse flow/stored/maintenance selection. Same slots, count,
  * enqueue credit and memory ports; no full-credit borrowing or new edge.
  */
class I1FlowResponseQueue[T <: Data](gen: T, entries: Int) extends Module {
    require(entries >= 2 && entries <= 16 && isPow2(entries))
    val io = IO(new QueueIO(gen, entries))
    val stored = IO(Output(gen.cloneType))
    val empty = IO(Output(Bool()))
    private val bits = log2Ceil(entries)
    private val payload = Mem(entries, gen.cloneType)
    private val pushPointer = RegInit(0.U(bits.W))
    private val popPointer = RegInit(0.U(bits.W))
    private val maybeFull = RegInit(false.B)
    private val equal = pushPointer === popPointer
    empty := equal && !maybeFull
    private val full = equal && maybeFull
    stored := payload.read(popPointer)
    io.enq.ready := !full
    io.deq.valid := !empty || io.enq.valid
    io.deq.bits := Mux(empty, io.enq.bits, stored)
    private val push = io.enq.fire && !(empty && io.deq.ready)
    private val pop = !empty && io.deq.ready
    when(push) {
        payload.write(pushPointer, io.enq.bits)
        pushPointer := pushPointer + 1.U
    }
    when(pop) { popPointer := popPointer + 1.U }
    when(push =/= pop) { maybeFull := push }
    io.count := Mux(equal, Mux(maybeFull, entries.U, 0.U),
        (pushPointer - popPointer)(bits - 1, 0))
}
