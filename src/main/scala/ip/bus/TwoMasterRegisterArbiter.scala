package soc.ip.bus

import chisel3._
import chisel3.util._

/** Fair register-request arbitration with ordered response ownership.
  * lockRequests requires each source to keep valid and payload until accepted,
  * except across common reset. It upgrades selection stability only; it cannot
  * repair a producer that withdraws an offered request. Existing callers retain
  * the original Decoupled selection behavior unless they explicitly opt in.
  */
class TwoMasterRegisterArbiter(capacity: Int = 8, lockRequests: Boolean = false,
    resetRoundRobin: Boolean = false) extends Module {
    require(capacity >= 2)
    val io = IO(new Bundle {
        val masters = Vec(2, Flipped(new RegisterPort))
        val downstream = new RegisterPort
    })
    // CDC-facing opt-in callers require a fully defined first transaction even
    // when master 1 is the first producer after cold reset. The library arbiter's
    // uninitialized lastGrant is legal two-state hardware, but can make its
    // selected output fire while an input READY remains X in four-state RTL.
    // Use one reset-defined selection for VALID, payload and both READY signals.
    // Default callers retain the original library arbitration implementation.
    val requests = if (resetRoundRobin) {
        val ports = Wire(new ArbiterIO(new RegisterRequest, 2))
        val last = RegInit(false.B)
        val chosen = Mux(ports.in(0).valid && ports.in(1).valid, !last, ports.in(1).valid)
        ports.chosen := chosen
        ports.out.valid := Mux(chosen, ports.in(1).valid, ports.in(0).valid)
        ports.out.bits := Mux(chosen, ports.in(1).bits, ports.in(0).bits)
        for (i <- 0 until 2) ports.in(i).ready := chosen === i.U && ports.out.ready
        when(ports.out.fire) { last := chosen }
        ports
    } else Module(new RRArbiter(new RegisterRequest, 2)).io
    val owners = Module(new Queue(UInt(1.W), capacity, pipe = false, flow = false))
    // Optional irrevocable offer for an external/CDC boundary. Lock only the
    // arbiter selection, not payload or acceptance: no added pipeline bubble,
    // one request/cycle and all original response-owner credits remain intact.
    val locked = if (lockRequests) Some(RegInit(false.B)) else None
    val lockedOwner = if (lockRequests) Some(Reg(UInt(1.W))) else None
    for (i <- 0 until 2) {
        requests.in(i).valid := io.masters(i).request.valid &&
            locked.map(value => !value || lockedOwner.get === i.U).getOrElse(true.B)
        requests.in(i).bits := io.masters(i).request.bits
        io.masters(i).request.ready := requests.in(i).ready &&
            locked.map(value => !value || lockedOwner.get === i.U).getOrElse(true.B)
        io.masters(i).response.valid := owners.io.deq.valid && owners.io.deq.bits === i.U &&
            io.downstream.response.valid
        io.masters(i).response.bits := io.downstream.response.bits
    }
    io.downstream.request.valid := requests.out.valid && owners.io.enq.ready
    io.downstream.request.bits := requests.out.bits
    requests.out.ready := io.downstream.request.ready && owners.io.enq.ready
    owners.io.enq.valid := io.downstream.request.fire
    owners.io.enq.bits := requests.chosen
    io.downstream.response.ready := owners.io.deq.valid &&
        Mux(owners.io.deq.bits === 0.U, io.masters(0).response.ready, io.masters(1).response.ready)
    owners.io.deq.ready := io.downstream.response.fire
    if (lockRequests) {
        when(locked.get) {
            assert(Mux(lockedOwner.get === 0.U, io.masters(0).request.valid, io.masters(1).request.valid),
                "locked register producer withdrew an unaccepted offer")
        }
        when(io.downstream.request.valid && !io.downstream.request.ready) {
            locked.get := true.B
            lockedOwner.get := requests.chosen
        }
        when(io.downstream.request.fire) { locked.get := false.B }
    }
    when(io.downstream.response.valid) { assert(owners.io.deq.valid, "register response without owner") }
}
