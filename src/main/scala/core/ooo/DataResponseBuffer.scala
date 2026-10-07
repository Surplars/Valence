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
  * idle covers queued responses only, not downstream outstanding requests.
  */
class DataResponseBuffer(registerPayload: Boolean = false, registerHead: Boolean = false) extends Module {
    require(!registerHead || registerPayload, "direct response head requires registered payload")
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val idle = Output(Bool())
    })
    io.downstream.request <> io.upstream.request
    val responses = if (registerHead)
        Module(new TwoEntryRegisterQueue(new DataResponse)).suggestName("responses").io
    else Module(new Queue(new DataResponse, 2, pipe = false, flow = !registerPayload)).suggestName("responses").io
    responses.enq <> io.downstream.response
    io.upstream.response <> responses.deq
    io.idle := responses.count === 0.U
}
