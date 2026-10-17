package soc.core.ooo

import chisel3._
import chisel3.util._
import hardfloat._

/** Unrounded, format-specific output. The significand retains guard/round/sticky
  * information: binary32 is never calculated as a rounded binary64 then narrowed.
  */
class FloatingPointRawResult(e: Int, s: Int) extends Bundle {
    val value = new RawFloat(e, s + 2)
    val invalid = Bool()
    val infinite = Bool()
}

class FloatingPointRawProducerIO(p: OooParams, e: Int, s: Int) extends Bundle {
    val flush = Input(Bool())
    val start = Flipped(Valid(new FloatingPointExecution(p)))
    // The single-owner parent keeps this context stable through completion.
    val rounding = Input(UInt(3.W))
    val result = Output(Valid(new FloatingPointRawResult(e, s)))
}

/** Raw add/multiply/FMA producer with no private rounding, token or result bank.
  * The selected raw output is captured by the format-level common register.
  * Add/multiply produce raw after one preparation edge; fused after two edges.
  * This preserves the previous normalization/rounding register boundary.
  */
class FloatingPointRawArithmetic(p: OooParams, double: Boolean, operation: String) extends Module {
    require(Set("add", "multiply", "fused").contains(operation))
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val io = IO(new FloatingPointRawProducerIO(p, e, s))
    override def desiredName: String = s"FloatingPointRaw${operation.capitalize}${if (double) "D" else "S"}"
    val prepared = RegNext(io.start.valid && !io.flush, false.B)
    when(io.flush) { prepared := false.B }
    def rec(lane: Int): UInt = recFNFromFN(e, s, FloatingPointFormat.operand(io.start.bits.operands(lane), double))
    io.result.bits.infinite := false.B
    if (operation == "fused") {
        val pre = Module(new MulAddRecFNToRaw_preMul(e, s))
        pre.io.op := Cat(io.start.bits.command.instruction(3), io.start.bits.command.instruction(2))
        pre.io.a := rec(0); pre.io.b := rec(1); pre.io.c := rec(2)
        val a = Reg(chiselTypeOf(pre.io.mulAddA))
        val b = Reg(chiselTypeOf(pre.io.mulAddB))
        val c = Reg(chiselTypeOf(pre.io.mulAddC))
        val metadata = Reg(chiselTypeOf(pre.io.toPostMul))
        when(io.start.valid && !io.flush) {
            a := pre.io.mulAddA; b := pre.io.mulAddB; c := pre.io.mulAddC
            metadata := pre.io.toPostMul
        }
        val product = Reg(UInt((2 * s + 1).W))
        val productMetadata = Reg(chiselTypeOf(pre.io.toPostMul))
        val productValid = RegNext(prepared && !io.flush, false.B)
        when(io.flush) { productValid := false.B }
        when(prepared && !io.flush) {
            product := (a * b) +& c
            productMetadata := metadata
        }
        val post = Module(new MulAddRecFNToRaw_postMul(e, s))
        post.io.fromPreMul := productMetadata
        post.io.mulAddResult := product
        post.io.roundingMode := io.rounding
        io.result.valid := productValid && !io.flush
        io.result.bits.value := post.io.rawOut
        io.result.bits.invalid := post.io.invalidExc
    } else {
        val a = Reg(new RawFloat(e, s))
        val b = Reg(new RawFloat(e, s))
        when(io.start.valid && !io.flush) {
            a := rawFloatFromRecFN(e, s, rec(0))
            b := rawFloatFromRecFN(e, s, rec(1))
        }
        io.result.valid := prepared && !io.flush
        if (operation == "add") {
            val subtract = Reg(Bool())
            when(io.start.valid && !io.flush) { subtract := io.start.bits.command.instruction(27) }
            val unit = Module(new AddRawFN(e, s))
            unit.io.a := a; unit.io.b := b
            unit.io.subOp := subtract
            unit.io.roundingMode := io.rounding
            io.result.bits.value := unit.io.rawOut
            io.result.bits.invalid := unit.io.invalidExc
        } else {
            val unit = Module(new MulRawFN(e, s))
            unit.io.a := a; unit.io.b := b
            io.result.bits.value := unit.io.rawOut
            io.result.bits.invalid := unit.io.invalidExc
        }
    }
}

/** Iterative divider/sqrt shares the same raw rounding boundary as add/mul/FMA.
  * The HardFloat pulse is captured immediately into the common raw register.
  * Flush resets the iterator, so no killed operation can emit a later pulse.
  */
class FloatingPointRawDivSqrt(p: OooParams, double: Boolean, enableDivide: Boolean, enableSqrt: Boolean)
    extends Module {
    require(enableDivide || enableSqrt)
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val io = IO(new FloatingPointRawProducerIO(p, e, s))
    override def desiredName: String = s"FloatingPointRawDivSqrt${if (double) "D" else "S"}"
    val unit = withReset(reset.asBool || io.flush) { Module(new DivSqrtRecFNToRaw_small(e, s, 0)) }
    val prepared = RegInit(false.B)
    val working = RegInit(false.B)
    val a = Reg(UInt((e + s + 1).W))
    val b = Reg(UInt((e + s + 1).W))
    val sqrt = Reg(Bool())
    when(io.start.valid && !io.flush) {
        assert(!prepared && !working && unit.io.inReady, "raw divider starts only with its one credit")
        prepared := true.B
        working := true.B
        a := recFNFromFN(e, s, FloatingPointFormat.operand(io.start.bits.operands(0), double))
        b := recFNFromFN(e, s, FloatingPointFormat.operand(io.start.bits.operands(1), double))
        sqrt := (if (!enableDivide) true.B else if (!enableSqrt) false.B
            else FloatingPointDecode.sqrt(io.start.bits.command.instruction))
    }
    unit.io.inValid := prepared && !io.flush
    unit.io.a := a; unit.io.b := b; unit.io.sqrtOp := sqrt
    unit.io.roundingMode := io.rounding
    when(unit.io.inValid && unit.io.inReady) { prepared := false.B }
    io.result.valid := (unit.io.rawOutValid_div || unit.io.rawOutValid_sqrt) && !io.flush
    io.result.bits.value := unit.io.rawOut
    io.result.bits.invalid := unit.io.invalidExc
    io.result.bits.infinite := unit.io.infiniteExc
    when(io.result.valid) {
        assert(working, "raw divider output belongs to a live request")
        working := false.B
    }
    when(io.flush) { prepared := false.B; working := false.B }
}

/** One format-specific round/pack unit shared by add, multiply, FMA, div and sqrt.
  * There is exactly one owner, one context register and one raw payload register.
  * Arbitration is BEFORE the raw register, never raw-register -> mux -> round.
  * Latency/II remain add/mul 3/4, FMA 4/5; divider iteration is unchanged.
  * Misc conversions retain their own correctly sized RoundAny implementations.
  */
class FloatingPointSharedArithmetic(p: OooParams, double: Boolean, c: FloatingPointConfig) extends Module {
    val io = IO(new FloatingPointProducerIO(p))
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    override def desiredName: String = s"FloatingPointSharedArithmetic${if (double) "D" else "S"}"
    val busy = RegInit(false.B)
    val valid = RegInit(false.B)
    val response = Reg(new FloatingPointResult(p))
    val rounding = Reg(UInt(3.W))
    val raw = Reg(new FloatingPointRawResult(e, s))
    val rawValid = RegInit(false.B)
    val inst = io.request.bits.command.instruction
    val producers = scala.collection.mutable.ArrayBuffer.empty[(Bool, FloatingPointRawProducerIO)]
    def connect(select: Bool, unit: FloatingPointRawProducerIO): Unit = {
        producers += ((select, unit))
        unit.flush := io.flush
        unit.rounding := rounding
        unit.start.bits := io.request.bits
        unit.start.valid := io.request.fire && select &&
            inst(26, 25) === (if (double) 1 else 0).U && io.request.bits.rounding <= 4.U
    }
    if (c.addSubtract) connect(FloatingPointDecode.add(inst),
        Module(new FloatingPointRawArithmetic(p, double, "add")).io)
    if (c.resources.sharedMultiplyFused && c.multiply && c.fusedMultiplyAdd) {
        connect(FloatingPointDecode.multiply(inst) || FloatingPointDecode.fused(inst),
            Module(new FloatingPointRawMultiplyFused(p, double)).io)
    } else {
        if (c.multiply) connect(FloatingPointDecode.multiply(inst),
            Module(new FloatingPointRawArithmetic(p, double, "multiply")).io)
        if (c.fusedMultiplyAdd) connect(FloatingPointDecode.fused(inst),
            Module(new FloatingPointRawArithmetic(p, double, "fused")).io)
    }
    if (c.divide || c.squareRoot) connect(
        (c.divide.B && FloatingPointDecode.divide(inst)) || (c.squareRoot.B && FloatingPointDecode.sqrt(inst)),
        Module(new FloatingPointRawDivSqrt(p, double, c.divide, c.squareRoot)).io)
    require(producers.nonEmpty)
    val supported = producers.map(_._1).reduce(_ || _) &&
        inst(26, 25) === (if (double) 1 else 0).U && io.request.bits.rounding <= 4.U
    io.request.ready := !busy && !io.flush
    io.result.valid := valid && !io.flush
    io.result.bits := response
    when(io.request.fire) {
        busy := true.B
        rounding := io.request.bits.rounding
        response := 0.U.asTypeOf(new FloatingPointResult(p))
        response.token := io.request.bits.command.token
        response.exception := !supported
        response.cause := Mux(supported, 0.U, 2.U)
        response.tval := Mux(supported, 0.U, inst.pad(64))
        when(!supported) { valid := true.B }
    }
    val results = producers.map(_._2.result)
    val produced = results.map(_.valid).reduce(_ || _)
    rawValid := produced && !io.flush
    when(produced && !io.flush) {
        assert(busy && !rawValid && !valid, "common raw register has exactly one live owner")
        raw := Mux1H(results.map(port => port.valid -> port.bits).toSeq)
    }
    val round = Module(new RoundRawFNToRecFN(e, s, 0))
    round.io.in := raw.value
    round.io.invalidExc := raw.invalid
    round.io.infiniteExc := raw.infinite
    round.io.roundingMode := rounding
    round.io.detectTininess := true.B
    when(rawValid && !io.flush) {
        response.value := FloatingPointFormat.canonical(fNFromRecFN(e, s, round.io.out),
            double, Some(raw.value.isNaN || raw.invalid))
        response.flags := round.io.exceptionFlags
        valid := true.B
    }
    when(io.result.fire) { busy := false.B; valid := false.B }
    when(io.flush) { busy := false.B; valid := false.B; rawValid := false.B }
    assert(PopCount(results.map(_.valid).toSeq) <= 1.U, "one raw FP producer per format")
}
