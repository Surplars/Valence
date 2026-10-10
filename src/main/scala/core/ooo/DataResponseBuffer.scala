package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.TwoEntryRegisterQueue

/** Ordered CPU response credits, including local MMIO and translation faults.
  * Capacity two, II=1, no mandatory empty-queue latency. Non-pipe enqueue
  * ready depends only on occupancy, not CPU ready. A full queue stalls even
  * on a simultaneous dequeue. Requests pass through without new ownership.
  * registerPayload removes empty-queue flow-through: minimum one response cycle,
  * same capacity/II/occupancy-only ready and reset/order/error ownership contract.
  * emptyFlow is an explicit local override for the two-register head only:
  * zero empty-response latency with both storage slots and non-pipe credits retained.
  * It forwards actual data/error/pageFault responses, never speculative store ACKs.
  * idle covers queued responses only, not downstream outstanding requests.
  */
class DataResponseBuffer(
    registerPayload: Boolean = false,
    registerHead: Boolean = false,
    emptyFlow: Boolean = false
) extends Module {
    require(!registerHead || registerPayload, "direct response head requires registered payload")
    require(!emptyFlow || registerHead, "local response flow requires the two-register response head")
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val idle = Output(Bool())
    })
    io.downstream.request <> io.upstream.request
    val responses = if (registerHead)
        Module(new TwoEntryRegisterQueue(new DataResponse)).suggestName("responses").io
    else Module(new Queue(new DataResponse, 2, pipe = false, flow = !registerPayload)).suggestName("responses").io
    if (emptyFlow) {
        // Old queued responses always win. An empty, accepted response consumes
        // no slot; an empty, held response is captured exactly once instead.
        // Downstream ready still depends only on the two original queue credits.
        val empty = !responses.deq.valid
        io.downstream.response.ready := responses.enq.ready
        responses.enq.valid := io.downstream.response.valid && !(empty && io.upstream.response.ready)
        responses.enq.bits := io.downstream.response.bits
        responses.deq.ready := io.upstream.response.ready
        io.upstream.response.valid := responses.deq.valid || io.downstream.response.valid
        io.upstream.response.bits := Mux(empty, io.downstream.response.bits, responses.deq.bits)
    } else {
        responses.enq <> io.downstream.response
        io.upstream.response <> responses.deq
    }
    io.idle := responses.count === 0.U
}
