package soc.core.ooo

import chisel3._
import chisel3.util._

/** Two-master fair, ordered memory boundary; capacity and backpressure contract: docs/dma.md.
  * Registered ownership removes request-ready -> empty-owner -> response-valid feedback.
  * It retains one request/cycle and eight owners. Same-cycle replies must hold valid/data
  * until accepted the following cycle; replies already delayed by >=1 cycle gain no latency.
  */
class SharedDataArbiter(registerResponseOwners: Boolean = false) extends Module {
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
    val owners = Module(new Queue(Bool(), 8, pipe = false, flow = !registerResponseOwners))
    io.memory.request.valid := Mux(selected, io.clients(1).request.valid, io.clients(0).request.valid) &&
        owners.io.enq.ready
    io.memory.request.bits  := Mux(selected, io.clients(1).request.bits, io.clients(0).request.bits)
    io.memoryRequestClient0 := !selected
    for (i <- 0 until 2) {
        io.clients(i).request.ready  := selected === i.U && owners.io.enq.ready && io.memory.request.ready
        io.clients(i).response.valid := owners.io.deq.valid && owners.io.deq.bits === i.U && io.memory.response.valid
        io.clients(i).response.bits  := io.memory.response.bits
    }
    owners.io.enq.valid      := io.memory.request.fire
    owners.io.enq.bits       := selected
    // Empty FIFO metadata is don't-care, never a dynamic Vec address. Scalar
    // selection also keeps the two-master mux explicit at this timing boundary.
    io.memory.response.ready := owners.io.deq.valid &&
        Mux(owners.io.deq.bits, io.clients(1).response.ready, io.clients(0).response.ready)
    owners.io.deq.ready      := io.memory.response.fire
    when(io.memory.request.valid && !io.memory.request.ready) { locked := true.B; lockedOwner := selected }
    when(io.memory.request.fire) { locked := false.B; turn := !selected }
}
