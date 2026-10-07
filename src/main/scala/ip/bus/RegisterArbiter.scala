package soc.ip.bus

import chisel3._
import chisel3.util._

/** Fair ordered two-master boundary. Four response owners, stable stalled offers.
  * Responses may not bypass the registered owner queue (zero-cycle slaves hold valid).
  */
class RegisterArbiter extends Module {
    val io = IO(new Bundle {
        val clients = Vec(2, Flipped(new RegisterPort))
        val memory = new RegisterPort
    })
    val turn = RegInit(false.B)
    val locked = RegInit(false.B)
    val lockedOwner = Reg(Bool())
    val selected = Mux(locked, lockedOwner,
        Mux(io.clients(0).request.valid && io.clients(1).request.valid, turn, io.clients(1).request.valid))
    val owners = Module(new Queue(Bool(), 4, pipe = false, flow = false))
    io.memory.request.valid := Mux(selected, io.clients(1).request.valid, io.clients(0).request.valid) &&
        owners.io.enq.ready
    io.memory.request.bits := Mux(selected, io.clients(1).request.bits, io.clients(0).request.bits)
    owners.io.enq.valid := io.memory.request.fire
    owners.io.enq.bits := selected
    for (i <- 0 until 2) {
        io.clients(i).request.ready := selected === i.U && owners.io.enq.ready && io.memory.request.ready
        io.clients(i).response.valid := owners.io.deq.valid && owners.io.deq.bits === i.U && io.memory.response.valid
        io.clients(i).response.bits := io.memory.response.bits
    }
    io.memory.response.ready := owners.io.deq.valid &&
        Mux(owners.io.deq.bits, io.clients(1).response.ready, io.clients(0).response.ready)
    owners.io.deq.ready := io.memory.response.fire
    when(io.memory.request.valid && !io.memory.request.ready) { locked := true.B; lockedOwner := selected }
    when(io.memory.request.fire) { locked := false.B; turn := !selected }
}
