package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.TwoEntryRegisterQueue

/** Core-local response envelope. Native fields keep their names and wire format;
  * optional translation provenance shares the response's exact queue owner.
  */
class OwnedDataResponse(returnHandleBits: Int = 0, guestFaultMetadata: Boolean = false)
    extends DataResponse(returnHandleBits) {
    val guestFault = if (guestFaultMetadata) Some(new GuestFaultMetadata) else None
}

/** Ordered CPU response credits, including local MMIO and translation faults.
  * Capacity two, II=1, no mandatory empty-queue latency. Non-pipe enqueue
  * ready depends only on occupancy, not CPU ready. A full queue stalls even
  * on a simultaneous dequeue. Requests pass through without new ownership.
  * registerPayload removes empty-queue flow-through: minimum one response cycle,
  * same capacity/II/occupancy-only ready and reset/order/error ownership contract.
  * emptyFlow is an explicit local override for the two-register head only:
  * zero empty-response latency with both storage slots and non-pipe credits retained.
  * It forwards actual data/error/pageFault responses, never speculative store ACKs.
  * Optional guest metadata uses the same two credits, enqueue/dequeue and live/head
  * selection as native response data, with no independent buffering or latency.
  * idle covers queued responses only, not downstream outstanding requests.
  */
class DataResponseBuffer(
    registerPayload: Boolean = false,
    registerHead: Boolean = false,
    emptyFlow: Boolean = false,
    returnConfig: Option[CpuReturnConfig] = None,
    guestFaultMetadata: Boolean = false
) extends Module {
    require(!registerHead || registerPayload, "direct response head requires registered payload")
    require(!emptyFlow || registerHead, "local response flow requires the two-register response head")
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort(returnConfig.map(_.handleBits).getOrElse(0)))
        val downstream = new DataPort(returnConfig.map(_.handleBits).getOrElse(0))
        val downstreamGuestFault = if (guestFaultMetadata) Some(Input(new GuestFaultMetadata)) else None
        val upstreamGuestFault = if (guestFaultMetadata) Some(Output(new GuestFaultMetadata)) else None
        val idle = Output(Bool())
    })
    io.downstream.request <> io.upstream.request
    private def responseType = new OwnedDataResponse(returnConfig.map(_.handleBits).getOrElse(0), guestFaultMetadata)
    val responses = if (registerHead)
        Module(new TwoEntryRegisterQueue(responseType)).suggestName("responses").io
    else Module(new Queue(responseType, 2, pipe = false, flow = !registerPayload)).suggestName("responses").io
    val live = Wire(responseType)
    CpuReturnTransport.responsePayload(live, io.downstream.response.bits)
    // responsePayload deliberately excludes reservation handles. Carry them
    // explicitly: neither an owned fault nor an empty flow may change the handle.
    live.returnHandle.foreach(_ := io.downstream.response.bits.returnHandle.get)
    live.guestFault.foreach(_ := io.downstreamGuestFault.get)
    responses.enq.bits := live
    io.downstream.response.ready := responses.enq.ready
    responses.deq.ready := io.upstream.response.ready
    val selected = Wire(responseType)
    if (emptyFlow) {
        // Old queued responses always win. An empty, accepted response consumes
        // no slot; an empty, held response is captured exactly once instead.
        // Downstream ready still depends only on the two original queue credits.
        val empty = !responses.deq.valid
        responses.enq.valid := io.downstream.response.valid && !(empty && io.upstream.response.ready)
        io.upstream.response.valid := responses.deq.valid || io.downstream.response.valid
        selected := Mux(empty, live, responses.deq.bits)
    } else {
        responses.enq.valid := io.downstream.response.valid
        io.upstream.response.valid := responses.deq.valid
        selected := responses.deq.bits
    }
    CpuReturnTransport.responsePayload(io.upstream.response.bits, selected)
    io.upstream.response.bits.returnHandle.foreach(_ := selected.returnHandle.get)
    io.upstreamGuestFault.foreach(_ := selected.guestFault.get)
    io.idle := responses.count === 0.U
}
