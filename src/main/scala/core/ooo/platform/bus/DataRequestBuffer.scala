package soc.core.ooo

import chisel3._
import chisel3.util._

/** Two-entry registered request boundary, no response data stage.
  * One request/cycle when draining; upstream ready depends on local occupancy,
  * never downstream ready. Preserve the CPU/DMA/walker classification with data.
  * Accepted requests are irrevocable; upstream retains response ownership.
  */
class DataRequestBuffer(entries: Int = 2, registerHead: Boolean = false) extends Module {
    require(entries >= 2)
    require(!registerHead || entries == 2)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val requestCpu = Input(Bool())
        val downstreamRequestCpu = Output(Bool())
        val idle = Output(Bool())
    })
    val payload = new Bundle {
        val request = new DataRequest
        val cpu = Bool()
    }
    val requests = if (registerHead) Module(new soc.ip.bus.TwoEntryRegisterQueue(payload)).io
        else Module(new Queue(payload, entries, pipe = false, flow = false)).io
    requests.enq.valid := io.upstream.request.valid
    requests.enq.bits.request := io.upstream.request.bits
    requests.enq.bits.cpu := io.requestCpu
    io.upstream.request.ready := requests.enq.ready
    io.downstream.request.valid := requests.deq.valid
    io.downstream.request.bits := requests.deq.bits.request
    // This narrow guard is queue-state-only. It prevents idle RAM contents
    // from becoming a native shift exponent in downstream GSIM assertions.
    io.downstream.request.bits.size := Mux(requests.deq.valid, requests.deq.bits.request.size, 0.U)
    requests.deq.ready := io.downstream.request.ready
    io.downstreamRequestCpu := requests.deq.bits.cpu
    io.upstream.response <> io.downstream.response
    io.idle := !requests.deq.valid
}
