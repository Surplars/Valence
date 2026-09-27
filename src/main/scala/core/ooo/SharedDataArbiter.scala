package soc.core.ooo

import chisel3._
import chisel3.util._

/** Two-master fair, ordered memory boundary; capacity and backpressure contract: docs/dma.md. */
class SharedDataArbiter extends Module {
    val io = IO(new Bundle {
        val clients = Vec(2, Flipped(new DataPort))
        val memory  = new DataPort
        val memoryRequestClient0 = Output(Bool())
    })
    val turn        = RegInit(false.B)
    val locked      = RegInit(false.B)
    val lockedOwner = Reg(Bool())
    val selected    = Mux(
        locked,
        lockedOwner,
        Mux(io.clients(0).request.valid && io.clients(1).request.valid, turn, io.clients(1).request.valid)
    )
    val owners = Module(new Queue(Bool(), 8, pipe = false, flow = true))
    io.memory.request.valid := io.clients(selected).request.valid && owners.io.enq.ready
    io.memory.request.bits  := io.clients(selected).request.bits
    io.memoryRequestClient0 := !selected
    for (i <- 0 until 2) {
        io.clients(i).request.ready  := selected === i.U && owners.io.enq.ready && io.memory.request.ready
        io.clients(i).response.valid := owners.io.deq.valid && owners.io.deq.bits === i.U && io.memory.response.valid
        io.clients(i).response.bits  := io.memory.response.bits
    }
    owners.io.enq.valid      := io.memory.request.fire
    owners.io.enq.bits       := selected
    io.memory.response.ready := owners.io.deq.valid && io.clients(owners.io.deq.bits).response.ready
    owners.io.deq.ready      := io.memory.response.fire
    when(io.memory.request.valid && !io.memory.request.ready) { locked := true.B; lockedOwner := selected }
    when(io.memory.request.fire) { locked := false.B; turn := !selected }
}
