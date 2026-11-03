package soc.core.inorder

import chisel3._
import chisel3.util._

/** Existing IF stage plus one skid slot: capacity 2, II=1 while not full.
  * Input READY depends only on registered occupancy, never downstream READY.
  * A full queue reopens one cycle after a pop. There is no extra fall-through
  * pipeline edge. Flush wins at the edge, and cancelInput discards ownership
  * while allowing unowned payload capture off the late recovery control path.
  */
class I1FetchQueue(p: FiveStageConfig) extends Module {
    val io = IO(new Bundle {
        val input = Flipped(Decoupled(new FiveStageInstruction(p)))
        val output = Decoupled(new FiveStageInstruction(p))
        val cancelInput = Input(Bool())
        val flush = Input(Bool())
    })
    val payload = Reg(Vec(2, new FiveStageInstruction(p)))
    val read = RegInit(false.B)
    val write = RegInit(false.B)
    val count = RegInit(0.U(2.W))
    io.input.ready := count =/= 2.U
    io.output.valid := count =/= 0.U
    io.output.bits := payload(read)
    val enqueue = io.input.fire && !io.cancelInput
    val dequeue = io.output.fire
    // Recovery qualifies only the small owner state, not the wide data CE.
    when(io.input.fire) { payload(write) := io.input.bits }
    when(enqueue) { write := !write }
    when(dequeue) { read := !read }
    when(enqueue =/= dequeue) { count := Mux(enqueue, count + 1.U, count - 1.U) }
    when(io.flush || reset.asBool) { read := false.B; write := false.B; count := 0.U }
    assert(count <= 2.U, "IF skid credit overflow")
}
