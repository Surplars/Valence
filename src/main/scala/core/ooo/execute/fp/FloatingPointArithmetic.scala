package soc.core.ooo

import chisel3._
import chisel3.util._
import hardfloat._

class FloatingPointProducerIO(p: OooParams) extends Bundle {
    val flush = Input(Bool())
    val request = Flipped(Decoupled(new FloatingPointExecution(p)))
    val result = Decoupled(new FloatingPointResult(p))
}

object FloatingPointFormat {
    def operand(value: UInt, double: Boolean): UInt =
        if (double) value else FloatingPointBits.operand(value, true.B)(31, 0)
    def canonical(value: UInt, double: Boolean, knownNaN: Option[Bool] = None): UInt = {
        val e = if (double) 11 else 8
        val s = if (double) 53 else 24
        // A producer's early classification avoids re-decoding the rounded IEEE
        // exponent/fraction on its critical output path. It must be equivalent
        // to output NaN, not merely to invalid (integer results can also be NV).
        val nan = knownNaN.getOrElse(value(e + s - 2, s - 1).andR && value(s - 2, 0).orR)
        val bits = Mux(nan, (if (double) BigInt("7ff8000000000000", 16)
            else BigInt("7fc00000", 16)).U((e + s).W), value)
        if (double) bits else FloatingPointBits.boxSingle(bits)
    }
}

/** Pinned HardFloat numerical implementation, with local IEEE/recFN adaptation.
  * Capacity one; add/sub and multiply latency 3, minimum II 4:
  * IEEE/boxing/recoding -> arithmetic/normalize -> round.
  * FMA latency 4, minimum II 5: pre-align -> product/add -> normalize -> round.
  * Full token and resolved rounding remain stable until the response is consumed.
  * Flush kills all stages; no speculative architectural writes.
  * These are explicit timing cuts, not a claim of 100 MHz FPGA qualification.
  */
class FloatingPointArithmetic(p: OooParams, double: Boolean, operation: String) extends Module {
    require(Set("add", "multiply", "fused").contains(operation))
    val io = IO(new FloatingPointProducerIO(p))
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    override def desiredName: String = s"FloatingPoint${operation.capitalize}${if (double) "D" else "S"}"
    val state = RegInit(0.U(3.W)) // 0 idle, 1 pre, 2 product, 3 raw, 4 response
    val response = Reg(new FloatingPointResult(p))
    val rounding = Reg(UInt(3.W))
    val legal = Reg(Bool())
    val raw = Reg(new RawFloat(e, s + 2))
    val invalid = Reg(Bool())
    val inst = io.request.bits.command.instruction
    val supported = (if (operation == "add") FloatingPointDecode.add(inst)
        else if (operation == "multiply") FloatingPointDecode.multiply(inst)
        else FloatingPointDecode.fused(inst)) && inst(26, 25) === (if (double) 1 else 0).U
    io.request.ready := state === 0.U && !io.flush
    io.result.valid := state === 4.U && !io.flush
    io.result.bits := response
    def rec(lane: Int): UInt = recFNFromFN(e, s, FloatingPointFormat.operand(io.request.bits.operands(lane), double))
    val round = Module(new RoundRawFNToRecFN(e, s, 0))
    round.io.in := raw
    round.io.invalidExc := invalid
    round.io.infiniteExc := false.B
    round.io.roundingMode := rounding
    round.io.detectTininess := true.B
    if (operation == "fused") {
        val pre = Module(new MulAddRecFNToRaw_preMul(e, s))
        pre.io.op := Cat(inst(3), inst(2))
        pre.io.a := rec(0); pre.io.b := rec(1); pre.io.c := rec(2)
        val a = Reg(chiselTypeOf(pre.io.mulAddA))
        val b = Reg(chiselTypeOf(pre.io.mulAddB))
        val c = Reg(chiselTypeOf(pre.io.mulAddC))
        val metadata = Reg(chiselTypeOf(pre.io.toPostMul))
        val product = Reg(UInt((2 * s + 1).W))
        val productMetadata = Reg(chiselTypeOf(pre.io.toPostMul))
        val post = Module(new MulAddRecFNToRaw_postMul(e, s))
        post.io.fromPreMul := productMetadata
        post.io.mulAddResult := product
        post.io.roundingMode := rounding
        when(io.request.fire) {
            a := pre.io.mulAddA; b := pre.io.mulAddB; c := pre.io.mulAddC
            metadata := pre.io.toPostMul
            state := 1.U
        }
        when(state === 1.U) {
            product := (a * b) +& c
            productMetadata := metadata
            state := 2.U
        }
        when(state === 2.U) {
            raw := post.io.rawOut; invalid := post.io.invalidExc
            state := 3.U
        }
    } else if (operation == "add") {
        val unit = Module(new AddRawFN(e, s))
        val a = Reg(new RawFloat(e, s))
        val b = Reg(new RawFloat(e, s))
        val subtract = Reg(Bool())
        unit.io.a := a
        unit.io.b := b
        unit.io.subOp := subtract
        unit.io.roundingMode := rounding
        when(io.request.fire) {
            a := rawFloatFromRecFN(e, s, rec(0))
            b := rawFloatFromRecFN(e, s, rec(1))
            subtract := inst(27)
            state := 1.U
        }
        when(state === 1.U) { raw := unit.io.rawOut; invalid := unit.io.invalidExc; state := 3.U }
    } else {
        val unit = Module(new MulRawFN(e, s))
        val a = Reg(new RawFloat(e, s))
        val b = Reg(new RawFloat(e, s))
        unit.io.a := a
        unit.io.b := b
        when(io.request.fire) {
            a := rawFloatFromRecFN(e, s, rec(0))
            b := rawFloatFromRecFN(e, s, rec(1))
            state := 1.U
        }
        when(state === 1.U) { raw := unit.io.rawOut; invalid := unit.io.invalidExc; state := 3.U }
    }
    when(io.request.fire) {
        rounding := io.request.bits.rounding
        legal := supported && io.request.bits.rounding <= 4.U
        response := 0.U.asTypeOf(new FloatingPointResult(p))
        response.token := io.request.bits.command.token
        response.exception := !(supported && io.request.bits.rounding <= 4.U)
        response.cause := Mux(supported && io.request.bits.rounding <= 4.U, 0.U, 2.U)
        response.tval := Mux(supported && io.request.bits.rounding <= 4.U, 0.U, inst.pad(64))
    }
    when(state === 3.U) {
        response.value := Mux(legal, FloatingPointFormat.canonical(fNFromRecFN(e, s, round.io.out),
            double, Some(raw.isNaN || invalid)), 0.U)
        response.flags := Mux(legal, round.io.exceptionFlags, 0.U)
        state := 4.U
    }
    when(io.result.fire) { state := 0.U }
    when(io.flush) { state := 0.U }
}

/** Resource-oriented one-bit-per-cycle divider/square-root.
  * Capacity one; IEEE/boxing/recoding is captured before the HardFloat launch.
  * Variable latency is one preparation cycle, iteration, then one rounding stage.
  * A private synchronous reset on flush kills the iteration as well as the token.
  * The raw-output pulse is buffered before rounding and supports arbitrary stalls.
  */
class FloatingPointDivSqrt(p: OooParams, double: Boolean, enableDivide: Boolean, enableSqrt: Boolean)
    extends Module {
    require(enableDivide || enableSqrt)
    val io = IO(new FloatingPointProducerIO(p))
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    override def desiredName: String = s"FloatingPointDivSqrt${if (double) "D" else "S"}"
    val working = RegInit(false.B)
    val prepared = RegInit(false.B)
    val rawValid = RegInit(false.B)
    val valid = RegInit(false.B)
    val response = Reg(new FloatingPointResult(p))
    val unit = withReset(reset.asBool || io.flush) { Module(new DivSqrtRecFNToRaw_small(e, s, 0)) }
    val inst = io.request.bits.command.instruction
    val sqrt = if (!enableDivide) true.B else if (!enableSqrt) false.B else FloatingPointDecode.sqrt(inst)
    val recodedA = Reg(UInt((e + s + 1).W))
    val recodedB = Reg(UInt((e + s + 1).W))
    val preparedSqrt = Reg(Bool())
    val preparedRounding = Reg(UInt(3.W))
    unit.io.sqrtOp := preparedSqrt
    unit.io.a := recodedA
    unit.io.b := recodedB
    unit.io.roundingMode := preparedRounding
    io.request.ready := !working && !prepared && !rawValid && !valid && unit.io.inReady && !io.flush
    unit.io.inValid := prepared && !io.flush
    when(unit.io.inValid && unit.io.inReady) { prepared := false.B }
    io.result.valid := valid && !io.flush
    io.result.bits := response
    val raw = Reg(chiselTypeOf(unit.io.rawOut))
    val invalid = Reg(Bool())
    val infinite = Reg(Bool())
    val rounding = Reg(UInt(3.W))
    val legal = Reg(Bool())
    val round = Module(new RoundRawFNToRecFN(e, s, 0))
    round.io.in := raw; round.io.invalidExc := invalid; round.io.infiniteExc := infinite
    round.io.roundingMode := rounding; round.io.detectTininess := true.B
    val supported = ((enableDivide.B && FloatingPointDecode.divide(inst)) ||
        (enableSqrt.B && FloatingPointDecode.sqrt(inst))) &&
        inst(26, 25) === (if (double) 1 else 0).U && io.request.bits.rounding <= 4.U
    when(io.request.fire) {
        working := true.B; prepared := true.B; legal := supported
        recodedA := recFNFromFN(e, s, FloatingPointFormat.operand(io.request.bits.operands(0), double))
        recodedB := recFNFromFN(e, s, FloatingPointFormat.operand(io.request.bits.operands(1), double))
        preparedSqrt := sqrt
        preparedRounding := io.request.bits.rounding
        response := 0.U.asTypeOf(new FloatingPointResult(p))
        response.token := io.request.bits.command.token
        response.exception := !supported; response.cause := Mux(supported, 0.U, 2.U)
        response.tval := Mux(supported, 0.U, inst.pad(64))
    }
    val produced = unit.io.rawOutValid_div || unit.io.rawOutValid_sqrt
    when(produced && !io.flush) {
        assert(working && !rawValid && !valid, "divider raw output must own exactly one full-token request")
        working := false.B; rawValid := true.B
        raw := unit.io.rawOut; invalid := unit.io.invalidExc; infinite := unit.io.infiniteExc
        rounding := unit.io.roundingModeOut
    }
    when(rawValid) {
        rawValid := false.B; valid := true.B
        response.value := Mux(legal, FloatingPointFormat.canonical(fNFromRecFN(e, s, round.io.out),
            double, Some(raw.isNaN || invalid)), 0.U)
        response.flags := Mux(legal, round.io.exceptionFlags, 0.U)
    }
    when(io.result.fire) { valid := false.B }
    when(io.flush) { working := false.B; prepared := false.B; rawValid := false.B; valid := false.B }
}
