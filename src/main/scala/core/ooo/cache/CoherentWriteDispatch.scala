package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.tilelink.LineWriteRequest

/** Retain queued write origins, with an explicit idle single-origin allocation.
  * If the writer stalls an offered direct payload, the same arbiter handshake
  * captures it into the empty queue, preserving that offer on the next cycle.
  */
class CoherentWriteDispatch(addressBits: Int, tagBits: Int) extends Module {
    val io = IO(new Bundle {
        val in = Flipped(Vec(2, Decoupled(new LineWriteRequest(addressBits, tagBits))))
        val out = Decoupled(new LineWriteRequest(addressBits, tagBits))
    })
    private val arbiter = Module(new RRArbiter(new LineWriteRequest(addressBits, tagBits), 2))
    private val queue = Module(new Queue(new LineWriteRequest(addressBits, tagBits), 2,
        pipe = false, flow = false))
    for (i <- 0 until 2) { arbiter.io.in(i) <> io.in(i) }
    private val directOffer = !queue.io.deq.valid && PopCount(io.in.map(_.valid)) === 1.U
    io.out.valid := queue.io.deq.valid || (directOffer && arbiter.io.out.valid)
    io.out.bits := Mux(queue.io.deq.valid, queue.io.deq.bits, arbiter.io.out.bits)
    private val directFire = !queue.io.deq.valid && io.out.fire
    queue.io.enq.valid := arbiter.io.out.valid && !directFire
    queue.io.enq.bits := arbiter.io.out.bits
    arbiter.io.out.ready := directFire || queue.io.enq.ready
    queue.io.deq.ready := io.out.ready
    when(directFire) { assert(arbiter.io.out.fire && !queue.io.enq.fire) }
}
