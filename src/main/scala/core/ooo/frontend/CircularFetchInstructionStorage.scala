package soc.core.ooo

import chisel3._
import chisel3.util._

/** Four static instruction slots with two-wide ordered capture and consumption.
  *
  * Minimum latency one, no bypass, capacity four, sustained input/output II=1.
  * Capture credit is OLD occupancy only, never same-cycle consumed capacity.
  * Two consecutive captures address different parity banks, each with two rows
  * and one payload write. Only the registered tail chooses payload placement;
  * late consumer acceptance changes head/count, never moves surviving payload.
  * Cancellation discards logical ownership, not payload, including dead writes
  * on that edge. Output validity deliberately does not depend on cancellation.
  *
  * Compared with fixed compacted head slots, the two full-payload outputs gain
  * a two-row bank read and a lane exchange mux. Only a third PC (not a third or
  * fourth full payload) is exposed for accepted-prefix path validation. This is
  * a control-cone tradeoff, not a demonstrated frequency/area improvement.
  */
class CircularFetchInstructionStorage extends Module {
    val io = IO(new Bundle {
        val capture = Input(Vec(2, Valid(new RawFetchInstruction)))
        val consume = Input(Vec(2, Bool()))
        val cancel = Input(Bool())
        val instructions = Output(Vec(2, Valid(new RawFetchInstruction)))
        val lookaheadPc = Output(Vec(3, UInt(64.W)))
        val occupancy = Output(UInt(3.W))
    })
    val banks = Seq.fill(2)(Reg(Vec(2, new RawFetchInstruction)))
    val head = RegInit(0.U(2.W))
    val tail = RegInit(0.U(2.W))
    val count = RegInit(0.U(3.W))
    val captured = PopCount(io.capture.map(_.valid))
    val consumed = PopCount(io.consume)
    val secondTail = (tail + 1.U)(1, 0)

    // Static row enables prevent a late consume/remaining calculation from
    // selecting any of the 904 resident payload bits or their write addresses.
    for (bank <- 0 until 2) {
        val first = tail(0) === bank.U
        val writing = Mux(first, io.capture(0).valid, io.capture(1).valid)
        val row = Mux(first, tail(1), secondTail(1))
        val payload = Mux(first, io.capture(0).bits, io.capture(1).bits)
        for (slot <- 0 until 2) {
            when(writing && row === slot.U) { banks(bank)(slot) := payload }
        }
    }

    // The even member of the oldest consecutive pair wraps to the next row
    // exactly when head is odd. Both full reads are shared between output lanes.
    val evenRow = head(1) ^ head(0)
    val even = Mux(evenRow, banks(0)(1), banks(0)(0))
    val odd = Mux(head(1), banks(1)(1), banks(1)(0))
    io.instructions(0).bits := Mux(head(0), odd, even)
    io.instructions(1).bits := Mux(head(0), even, odd)
    for (lane <- 0 until 2) {
        io.instructions(lane).valid := count > lane.U
        io.lookaheadPc(lane) := io.instructions(lane).bits.pc
    }
    val thirdEvenPc = Mux(head(1), banks(0)(0).pc, banks(0)(1).pc)
    val thirdOddPc = Mux(head(1), banks(1)(0).pc, banks(1)(1).pc)
    io.lookaheadPc(2) := Mux(head(0), thirdOddPc, thirdEvenPc)
    io.occupancy := count

    head := (head + consumed)(1, 0)
    tail := (tail + captured)(1, 0)
    count := count - consumed + captured
    when(io.cancel) {
        head := 0.U
        tail := 0.U
        count := 0.U
    }
    assert(count <= 4.U, "circular fetch storage capacity exceeded")
    assert(tail === (head + count)(1, 0), "circular fetch storage pointers lost ordered ownership")
    assert(!io.capture(1).valid || io.capture(0).valid, "circular fetch captures must form a prefix")
    assert(captured <= 4.U - count, "circular fetch capture must not borrow consumed credit")
    assert(!io.consume(1) || io.consume(0), "circular fetch consumption must form a prefix")
    assert(consumed <= count, "circular fetch consumed an empty owner")
}
