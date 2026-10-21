package soc.ip.interrupt

import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterPort, RegisterRequest}

/** Opt-in, single-clock MSI admission hold. STOP is not cancellation or reset.
  *
  * Capture before advertising at the downstream boundary: a STOP can reject a
  * new upstream offer, but can never withdraw an already advertised request.
  * Accepted requests, downstream replies and terminal response consumption all
  * continue while stopped. Upstream pending-but-unaccepted interrupts do not
  * prevent idle. The surrounding APLIC retains their architectural state.
  *
  * Both endpoints must share this reset. Reset discards the entire common
  * transaction epoch; resetting just this ledger with live peers is unsupported.
  * This is not a CDC, clock gate, or an IMSIC-pending/CPU-interrupt idle detector.
  */
class MsiAdmissionBarrier(capacity: Int = 8) extends Module {
    require(capacity >= 1)
    val io = IO(new Bundle {
        val stop = Input(Bool())
        val source = Flipped(new RegisterPort)
        val destination = new RegisterPort
        val idle = Output(Bool())
    })

    private val width = log2Ceil(capacity + 1)
    private val admitted = RegInit(0.U(width.W))
    private val issued = RegInit(0.U(width.W))
    private val requests = Module(new Queue(new RegisterRequest, 1, pipe = false, flow = false))
    private val room = admitted < capacity.U
    requests.io.enq.valid := io.source.request.valid && !io.stop && room
    requests.io.enq.bits := io.source.request.bits
    io.source.request.ready := requests.io.enq.ready && !io.stop && room
    io.destination.request <> requests.io.deq

    // A zero-latency endpoint may reply on the actual downstream acceptance
    // edge. Merely having an admitted but not yet issued owner is insufficient.
    private val responseOwner = issued =/= 0.U || io.destination.request.fire
    io.source.response.valid := io.destination.response.valid && responseOwner
    io.source.response.bits := io.destination.response.bits
    io.destination.response.ready := io.source.response.ready && responseOwner
    private val accept = io.source.request.fire
    private val issue = io.destination.request.fire
    private val retire = io.source.response.fire
    when(accept =/= retire) { admitted := Mux(accept, admitted + 1.U, admitted - 1.U) }
    when(issue =/= retire) { issued := Mux(issue, issued + 1.U, issued - 1.U) }
    io.idle := admitted === 0.U

    assert(admitted <= capacity.U, "MSI admitted owner overflow")
    assert(issued <= admitted, "MSI issued owner exceeds admitted owners")
    assert(admitted === issued +& requests.io.count, "MSI request/response ledger mismatch")
    when(accept) { assert(admitted < capacity.U, "MSI acceptance without credit") }
    when(retire) { assert(admitted =/= 0.U, "MSI terminal response underflow") }
    when(io.destination.response.valid) {
        assert(responseOwner, "MSI response without issued owner")
    }
    when(io.stop) { assert(!accept, "MSI new admission while stopped") }
}
