package soc.ip.bus

import chisel3._
import chisel3.util._

/** Fair register-request arbitration with ordered response ownership. */
class TwoMasterRegisterArbiter(capacity: Int = 8) extends Module {
    require(capacity >= 2)
    val io = IO(new Bundle {
        val masters = Vec(2, Flipped(new RegisterPort))
        val downstream = new RegisterPort
    })
    val requests = Module(new RRArbiter(new RegisterRequest, 2))
    val owners = Module(new Queue(UInt(1.W), capacity, pipe = false, flow = false))
    for (i <- 0 until 2) {
        requests.io.in(i).valid := io.masters(i).request.valid
        requests.io.in(i).bits := io.masters(i).request.bits
        io.masters(i).request.ready := requests.io.in(i).ready
        io.masters(i).response.valid := owners.io.deq.valid && owners.io.deq.bits === i.U &&
            io.downstream.response.valid
        io.masters(i).response.bits := io.downstream.response.bits
    }
    io.downstream.request.valid := requests.io.out.valid && owners.io.enq.ready
    io.downstream.request.bits := requests.io.out.bits
    requests.io.out.ready := io.downstream.request.ready && owners.io.enq.ready
    owners.io.enq.valid := io.downstream.request.fire
    owners.io.enq.bits := requests.io.chosen
    io.downstream.response.ready := owners.io.deq.valid &&
        Mux(owners.io.deq.bits === 0.U, io.masters(0).response.ready, io.masters(1).response.ready)
    owners.io.deq.ready := io.downstream.response.fire
    when(io.downstream.response.valid) { assert(owners.io.deq.valid, "register response without owner") }
}
