package soc.core.ooo

import chisel3._
import chisel3.util._

/** II=1 multiplier. Optional operand capture adds one cycle to the 2/6-cycle arithmetic.
  * Slots are reserved on acceptance, including the input stage; cancellation and
  * token checks still apply to every reservation. Contract: docs/rv64m.md.
  */
class PipelinedMultiply(p: OooParams) extends Module {
    val capacity = 8
    val io       = IO(new Bundle {
        val start    = Flipped(Decoupled(new MultiplyDivideRequest(p)))
        val complete = Decoupled(new BackendCompletion(p))
        val wordPreview = Output(Valid(new BackendCompletion(p)))
        val cancel   = Input(Vec(capacity, Bool()))
        val live     = Output(Vec(capacity, Bool()))
        val owner    = Output(Vec(capacity, new RobToken(p)))
        val busy     = Output(Bool())
    })
    val head    = RegInit(0.U(3.W))
    val tail    = RegInit(0.U(3.W))
    val count   = RegInit(0.U(4.W))
    val live    = RegInit(VecInit(Seq.fill(capacity)(false.B)))
    val done    = RegInit(VecInit(Seq.fill(capacity)(false.B)))
    val entries = Reg(Vec(capacity, new BackendCompletion(p)))
    io.live := live
    for (i <- 0 until capacity) {
        io.owner(i) := Mux(live(i), entries(i).token, 0.U.asTypeOf(new RobToken(p)))
        when(io.cancel(i) && live(i)) { live(i) := false.B }
    }
    io.busy           := count =/= 0.U
    io.start.ready    := count < capacity.U
    io.complete.valid := count =/= 0.U && live(head) && done(head)
    io.complete.bits  := Mux(io.complete.valid, entries(head), 0.U.asTypeOf(new BackendCompletion(p)))
    val pop = count =/= 0.U && (!live(head) || io.complete.fire)
    when(pop) {
        live(head) := false.B
        done(head) := false.B
        head       := head + 1.U
    }
    when(io.start.fire =/= pop) { count := Mux(io.start.fire, count + 1.U, count - 1.U) }
    when(io.start.fire) {
        assert(!live(tail), "multiplier result reservation overwrite")
        assert(!io.start.bits.operation(2) && (!io.start.bits.word || io.start.bits.operation === 0.U))
        live(tail)           := true.B
        done(tail)           := false.B
        entries(tail)        := 0.U.asTypeOf(new BackendCompletion(p))
        entries(tail).token  := io.start.bits.token
        entries(tail).nextPc := io.start.bits.pc + 4.U
        tail                 := tail + 1.U
    }
    // Pipeline never stalls: every input owns a result slot before arithmetic starts.
    // Do not put PRF owner selection and a DSP multiply in the same cycle.
    // Capture AFTER the original handshake: pending clears and slot accounting
    // are unchanged. A cancelled reservation may traverse the arithmetic, but
    // cannot write a reused result slot without the original token tag match.
    val arithmeticFire = if (p.registeredMulDivOperands) RegNext(io.start.fire, false.B) else io.start.fire
    val operands = if (p.registeredMulDivOperands) RegEnable(io.start.bits, io.start.fire) else io.start.bits
    val arithmeticSlot = if (p.registeredMulDivOperands) RegEnable(tail, io.start.fire) else tail
    val valid      = RegInit(VecInit(Seq.fill(5)(false.B)))
    val slots      = Reg(Vec(5, UInt(3.W)))
    val tags       = Reg(Vec(5, UInt(p.tagBits.W)))
    val correction = Reg(Vec(5, UInt(64.W)))
    val high       = Reg(Vec(5, Bool()))
    val word       = Reg(Vec(5, Bool()))
    valid(0) := arithmeticFire
    when(arithmeticFire) {
        slots(0) := arithmeticSlot
        tags(0)  := operands.token.tag
        val signedA = operands.operation === 1.U || operands.operation === 2.U
        val signedB = operands.operation === 1.U
        correction(0) := Mux(signedA && operands.left(63), operands.right, 0.U) +
            Mux(signedB && operands.right(63), operands.left, 0.U)
        high(0) := operands.operation =/= 0.U
        word(0) := operands.word
    }
    for (i <- 1 until 5) {
        valid(i) := valid(i - 1)
        when(valid(i - 1)) {
            slots(i)      := slots(i - 1)
            tags(i)       := tags(i - 1)
            correction(i) := correction(i - 1)
            high(i)       := high(i - 1)
            word(i)       := word(i - 1)
        }
    }
    val partial = Reg(Vec(16, UInt(32.W)))
    val pairs   = Reg(Vec(8, UInt(48.W)))
    val rows    = Reg(Vec(4, UInt(80.W)))
    val halves  = Reg(Vec(2, UInt(96.W)))
    val product = Reg(UInt(128.W))
    for (i <- 0 until 4; j <- 0 until 4) {
        val wordTerm = (i == 0 && j <= 1) || (i == 1 && j == 0)
        when(arithmeticFire && (!operands.word || wordTerm.B)) {
            partial(i * 4 + j) := operands.left(16 * j + 15, 16 * j) * operands.right(16 * i + 15, 16 * i)
        }
    }
    for (i <- 0 until 8) {
        when(valid(0) && !word(0)) {
            pairs(i) := partial(2 * i) + (partial(2 * i + 1) << 16)
        }
    }
    // MULW needs only p00 and the low halves of p01/p10. Keep the 16x16 products
    // registered, then finish the cross-term and 32-bit sum in the following cycle.
    val wordSlot = Mux(valid(0), slots(0), 0.U)
    val wordCross = partial(1)(15, 0) +& partial(4)(15, 0)
    val wordLow = partial(0) + (wordCross(15, 0) << 16)
    // Registered partial products can wake a dependent operation before the result-slot write.
    // Cancellation is enforced at the ROB boundary; do not feed redirect-dependent cancel into this path.
    io.wordPreview.valid := valid(0) && word(0) && live(wordSlot) &&
        entries(wordSlot).token.tag === tags(0)
    io.wordPreview.bits := entries(wordSlot)
    io.wordPreview.bits.data := Cat(Fill(32, wordLow(31)), wordLow(31, 0))
    when(valid(0) && word(0) && live(wordSlot) && entries(wordSlot).token.tag === tags(0)) {
        entries(wordSlot).data := Cat(Fill(32, wordLow(31)), wordLow(31, 0))
        done(wordSlot)         := true.B
    }
    for (i <- 0 until 4) {
        when(valid(1) && !word(1)) { rows(i) := pairs(2 * i) + (pairs(2 * i + 1) << 32) }
    }
    for (i <- 0 until 2) {
        when(valid(2) && !word(2)) { halves(i) := rows(2 * i) + (rows(2 * i + 1) << 16) }
    }
    when(valid(3) && !word(3)) { product := halves(0) + (halves(1) << 32) }
    val slot   = Mux(valid(4), slots(4), 0.U)
    val upper  = product(127, 64) - correction(4)
    val result = Mux(high(4), upper, product(63, 0))
    when(valid(4) && !word(4) && live(slot) && entries(slot).token.tag === tags(4)) {
        entries(slot).data := result
        done(slot)         := true.B
    }
    assert(count <= capacity.U)
}
