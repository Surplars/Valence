package soc.core.ooo

import chisel3._
import chisel3.util._

/** Registered redirect mailbox, standalone-testable and used by the explicit execution-mailbox backend.
  *
  * Capacity 1, minimum latency 1, no empty bypass, sustained II 1 with turnover.
  * Two physical execution holders offer full-token resolutions. Registered owner
  * age selects one before late cancellation authorizes capture. A killed oldest
  * winner never falls back to the younger offer. `capture`, not merely `valid`,
  * is the event that may set the source holder's resolved-once bit.
  *
  * Source lifecycle: resolved becomes true only after this source's capture and
  * clears only for a new physical holder owner or its cancellation. The mailbox
  * suppresses duplicate current owners, including same-edge drain; it does not
  * retain an unbounded history of consumed tokens. Two physical sources may NOT
  * present the same full token: that violates holder ownership and is asserted,
  * rather than claiming that acknowledging one source resolves its illegal alias.
  * A fresh generation at the same ROB index is a different owner. Inputs do not
  * authorize architectural effects.
  *
  * Ordinary output backpressure retains valid and payload. Explicit cancelHeld or
  * flush may withdraw that old owner. Neither cancellation lends input credit;
  * a full cancelled mailbox with output.ready=false becomes available next cycle.
  */
class BranchResolutionMailbox(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val offer = Input(Vec(2, Valid(new FrontendRedirect(p))))
        val sourceResolved = Input(UInt(2.W))
        val killed = Input(UInt(2.W))
        val flush = Input(Bool())
        val cancelHeld = Input(Bool())
        val out = Decoupled(new FrontendRedirect(p))
        val capture = Output(UInt(2.W))
        val winner = Output(UInt(2.W))
        val duplicate = Output(UInt(2.W))
        val occupied = Output(Bool())
        val canCapture = Output(Bool())
    })
    val occupied = RegInit(false.B)
    val payload = RegInit(0.U.asTypeOf(new FrontendRedirect(p)))
    io.occupied := occupied
    io.out.valid := occupied && !io.flush && !io.cancelHeld
    io.out.bits := payload
    io.canCapture := !occupied || io.out.ready
    assert(!(io.offer(0).valid && io.offer(1).valid &&
        io.offer(0).bits.token.asUInt === io.offer(1).bits.token.asUInt),
        "resolution sources must own distinct full tokens")

    val duplicate = (0 until 2).map { lane =>
        val held = occupied && io.offer(lane).bits.token.asUInt === payload.token.asUInt
        val earlier = (0 until lane).map(other => io.offer(other).valid &&
            io.offer(other).bits.token.asUInt === io.offer(lane).bits.token.asUInt)
            .foldLeft(false.B)(_ || _)
        io.offer(lane).valid && (held || earlier)
    }
    io.duplicate := VecInit(duplicate).asUInt
    val eligible = (0 until 2).map(lane => io.offer(lane).valid &&
        !io.sourceResolved(lane) && !duplicate(lane))
    val age = io.offer.map(offer => (offer.bits.token.index - io.head)(p.robBits - 1, 0))
    val first = eligible(0) && (!eligible(1) || age(0) <= age(1))
    val second = eligible(1) && (!eligible(0) || age(1) < age(0))
    io.winner := Cat(second, first)
    io.capture := io.winner & ~io.killed & Fill(2, io.canCapture && !io.flush)

    when(io.flush || io.cancelHeld || io.out.fire) { occupied := false.B }
    when(io.capture.orR) {
        payload := Mux1H((0 until 2).map(lane => io.capture(lane) -> io.offer(lane).bits))
        occupied := true.B
    }
    assert(PopCount(io.winner) <= 1.U && PopCount(io.capture) <= 1.U,
        "one branch resolution owner per mailbox capture")
    assert(!(io.capture & (io.sourceResolved | io.duplicate | io.killed)).orR,
        "captured resolution must be new, unresolved and survive current cancellation")
    when(occupied && !io.out.ready) {
        assert(!io.capture.orR, "late cancellation must not lend same-cycle mailbox capacity")
    }
    val stalled = RegNext(io.out.valid && !io.out.ready, false.B)
    val stalledPayload = RegEnable(io.out.bits.asUInt, io.out.valid && !io.out.ready)
    when(stalled && !io.flush && !io.cancelHeld) {
        assert(io.out.valid && io.out.bits.asUInt === stalledPayload,
            "ordinary backpressure retains the complete resolution owner and payload")
    }
}
