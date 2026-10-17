package soc.core.ooo

import chisel3._
import chisel3.util._

/** Registered instruction request boundary: capacity 2, latency 1, II 1.
  * Address and word mask are captured atomically. Occupancy-only enqueue ready
  * cuts downstream arbitration from the translation-state enable. Responses,
  * including both precise fault vectors, retain their original backpressure.
  * No response ownership is invented or released by accepting a queued request.
  */
class InstructionRequestBuffer(packetWords: Int = 2, flowThrough: Boolean = false,
    independentCapture: Boolean = false) extends Module {
    require(Set(2, 4).contains(packetWords))
    val io = IO(new Bundle {
        val upstream = Flipped(new InstructionPort(packetWords))
        val downstream = new InstructionPort(packetWords)
    })
    class Request extends Bundle {
        val address = UInt(64.W)
        val mask = UInt(packetWords.W)
    }
    require(!independentCapture || flowThrough, "independent capture requires the empty bypass")
    if (independentCapture) {
        // Capacity/visible timing are identical to Queue(flow=true, pipe=false).
        // Capture every accepted offer, even a bypassed one. Such speculative
        // data is invisible while empty; no downstream ready reaches RAM WE.
        val storage = Mem(2, new Request)
        val enqueue = RegInit(false.B)
        val dequeue = RegInit(false.B)
        val maybeFull = RegInit(false.B)
        val same = enqueue === dequeue
        val empty = same && !maybeFull
        val full = same && maybeFull
        io.upstream.request.ready := !full
        io.downstream.request.valid := !empty || io.upstream.request.valid
        val saved = storage(dequeue)
        io.downstream.request.bits := Mux(empty, io.upstream.request.bits, saved.address)
        io.downstream.requestMask := Mux(empty, io.upstream.requestMask, saved.mask)
        val capture = io.upstream.request.fire
        val push = capture && !(empty && io.downstream.request.ready)
        val pop = io.downstream.request.fire && !empty
        when(capture) {
            val payload = Wire(new Request)
            payload.address := io.upstream.request.bits
            payload.mask := io.upstream.requestMask
            storage(enqueue) := payload
        }
        when(push) { enqueue := !enqueue }
        when(pop) { dequeue := !dequeue }
        when(push =/= pop) { maybeFull := push }
    } else {
        // Empty flow changes dequeue only; ready never borrows downstream credit.
        val requests = Module(new Queue(new Request, 2, pipe = false, flow = flowThrough))
        requests.io.enq.valid := io.upstream.request.valid
        requests.io.enq.bits.address := io.upstream.request.bits
        requests.io.enq.bits.mask := io.upstream.requestMask
        io.upstream.request.ready := requests.io.enq.ready
        io.downstream.request.valid := requests.io.deq.valid
        io.downstream.request.bits := requests.io.deq.bits.address
        io.downstream.requestMask := requests.io.deq.bits.mask
        requests.io.deq.ready := io.downstream.request.ready
    }
    io.upstream.response <> io.downstream.response
    io.upstream.responseError := io.downstream.responseError
    io.upstream.responsePageFault := io.downstream.responsePageFault
}
