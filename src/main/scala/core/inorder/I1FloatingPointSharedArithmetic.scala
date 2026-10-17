// Arithmetic/IEEE adapter copied from the local pinned-HardFloat integration; no OoO state/control.
// Provenance: src/main/scala/core/ooo/FloatingPointSharedArithmetic.scala. Keep numerical changes independently SoftFloat-tested.
package soc.core.inorder

import chisel3._
import chisel3.util._
import hardfloat._

/** Unrounded, format-specific output. The significand retains guard/round/sticky
  * information: binary32 is never calculated as a rounded binary64 then narrowed.
  */
class I1FloatingPointRawResult(e: Int, s: Int) extends Bundle {
    val value = new RawFloat(e, s + 2)
    val invalid = Bool()
    val infinite = Bool()
}

class I1FloatingPointRawProducerIO(p: FiveStageConfig, e: Int, s: Int) extends Bundle {
    val flush = Input(Bool())
    val start = Flipped(Valid(new I1FloatingPointExecution(p)))
    // The single-owner parent keeps this context stable through completion.
    val rounding = Input(UInt(3.W))
    val result = Output(Valid(new I1FloatingPointRawResult(e, s)))
}

/** Raw add/multiply/FMA producer with no private rounding, token or result bank.
  * The selected raw output is captured by the format-level common register.
  * Add/multiply produce raw after one preparation edge; fused after two edges.
  * This preserves the previous normalization/rounding register boundary.
  */
class I1FloatingPointRawArithmetic(p: FiveStageConfig, double: Boolean, operation: String) extends Module {
    require(Set("add", "multiply", "fused").contains(operation))
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val io = IO(new I1FloatingPointRawProducerIO(p, e, s))
    override def desiredName: String = s"I1FloatingPointRaw${operation.capitalize}${if (double) "D" else "S"}"
    val prepared = RegNext(io.start.valid && !io.flush, false.B)
    when(io.flush) { prepared := false.B }
    def rec(lane: Int): UInt = recFNFromFN(e, s, I1FloatingPointFormat.operand(io.start.bits.operands(lane), double))
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
class I1FloatingPointRawDivSqrt(p: FiveStageConfig, double: Boolean, enableDivide: Boolean, enableSqrt: Boolean,
    preparedNormalization: Boolean = false)
    extends Module {
    require(enableDivide || enableSqrt)
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val io = IO(new I1FloatingPointRawProducerIO(p, e, s))
    val normalization = if (preparedNormalization)
        Some(IO(Input(Vec(2, UInt(log2Ceil(s).W))))) else None
    override def desiredName: String = s"I1FloatingPointRawDivSqrt${if (double) "D" else "S"}"
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
        val recoded = (0 until 2).map { lane =>
            val ieee = I1FloatingPointFormat.operand(io.start.bits.operands(lane), double)
            if (preparedNormalization) {
                val preparedRec = I1FloatingPointPredecodedRecoder(e, s, ieee, normalization.get(lane))
                assert(normalization.get(lane) === countLeadingZeros(ieee(s - 2, 0)) &&
                    preparedRec === recFNFromFN(e, s, ieee),
                    "prepared FP normalization belongs to the exact captured operand")
                preparedRec
            } else recFNFromFN(e, s, ieee)
        }
        a := recoded(0)
        b := recoded(1)
        sqrt := (if (!enableDivide) true.B else if (!enableSqrt) false.B
            else I1FloatingPointDecode.sqrt(io.start.bits.command.instruction))
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
  * Compact latency/II remain add/mul 3/4, FMA 4/5. Optional FPGA cuts add
  * mask/increment/recoded boundaries; divider iteration itself is unchanged.
  * Misc conversions retain their own correctly sized RoundAny implementations.
  */
class I1FloatingPointSharedArithmetic(p: FiveStageConfig, double: Boolean, c: I1FloatingPointConfig,
    preparedNormalization: Boolean = false) extends Module {
    val io = IO(new I1FloatingPointProducerIO(p))
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    require(!preparedNormalization || p.fpgaTimingCuts)
    val normalization = if (preparedNormalization)
        Some(IO(Input(Vec(3, UInt(log2Ceil(s).W))))) else None
    override def desiredName: String = s"I1FloatingPointSharedArithmetic${if (double) "D" else "S"}"
    val busy = RegInit(false.B)
    val valid = RegInit(false.B)
    val response = Reg(new I1FloatingPointResult(p))
    val rounding = Reg(UInt(3.W))
    val raw = Reg(new I1FloatingPointRawResult(e, s))
    val rawValid = RegInit(false.B)
    val inst = io.request.bits.command.instruction
    val producers = scala.collection.mutable.ArrayBuffer.empty[(Bool, I1FloatingPointRawProducerIO)]
    def connect(select: Bool, unit: I1FloatingPointRawProducerIO): Unit = {
        producers += ((select, unit))
        unit.flush := io.flush
        unit.rounding := rounding
        unit.start.bits := io.request.bits
        unit.start.valid := io.request.fire && select &&
            inst(26, 25) === (if (double) 1 else 0).U && io.request.bits.rounding <= 4.U
    }
    if (c.addSubtract) {
        if (p.fpgaTimingCuts) {
            val add = Module(new I1FloatingPointRawAddCuts(p, double, preparedNormalization))
            add.normalization.foreach(_ := VecInit(normalization.get.take(2)))
            connect(I1FloatingPointDecode.add(inst), add.io)
        } else connect(I1FloatingPointDecode.add(inst),
            Module(new I1FloatingPointRawArithmetic(p, double, "add")).io)
    }
    if (c.resources.sharedMultiplyFused && c.multiply && c.fusedMultiplyAdd) {
        val multiply = Module(new I1FloatingPointRawMultiplyFused(p, double, preparedNormalization))
        multiply.normalization.foreach(_ := normalization.get)
        connect(I1FloatingPointDecode.multiply(inst) || I1FloatingPointDecode.fused(inst),
            multiply.io)
    } else {
        if (c.multiply) connect(I1FloatingPointDecode.multiply(inst),
            Module(new I1FloatingPointRawArithmetic(p, double, "multiply")).io)
        if (c.fusedMultiplyAdd) connect(I1FloatingPointDecode.fused(inst),
            Module(new I1FloatingPointRawArithmetic(p, double, "fused")).io)
    }
    if (c.divide || c.squareRoot) {
        val divide = Module(new I1FloatingPointRawDivSqrt(p, double, c.divide, c.squareRoot,
            preparedNormalization))
        divide.normalization.foreach(_ := VecInit(normalization.get.take(2)))
        connect((c.divide.B && I1FloatingPointDecode.divide(inst)) ||
            (c.squareRoot.B && I1FloatingPointDecode.sqrt(inst)), divide.io)
    }
    require(producers.nonEmpty)
    val supported = producers.map(_._1).reduce(_ || _) &&
        inst(26, 25) === (if (double) 1 else 0).U && io.request.bits.rounding <= 4.U
    io.request.ready := !busy && !io.flush
    io.completed := valid
    io.result.valid := io.completed && !io.flush
    io.result.bits := response
    when(io.request.fire) {
        busy := true.B
        rounding := io.request.bits.rounding
        response := 0.U.asTypeOf(new I1FloatingPointResult(p))
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
    val roundedValue = Wire(UInt((e + s + 1).W))
    val roundedFlags = Wire(UInt(5.W))
    val roundedNaN = Wire(Bool())
    val roundedValid = Wire(Bool())
    if (p.fpgaTimingCuts) {
        val round = Module(new I1FloatingPointRoundCuts(e, s))
        round.io.flush := io.flush; round.io.start.valid := rawValid
        round.io.start.bits := raw; round.io.rounding := rounding
        roundedValue := round.io.result.bits.value; roundedFlags := round.io.result.bits.flags
        roundedNaN := round.io.result.bits.nan; roundedValid := round.io.result.valid
    } else {
        val round = Module(new RoundRawFNToRecFN(e, s, 0))
        round.io.in := raw.value; round.io.invalidExc := raw.invalid; round.io.infiniteExc := raw.infinite
        round.io.roundingMode := rounding; round.io.detectTininess := true.B
        roundedValue := round.io.out; roundedFlags := round.io.exceptionFlags
        roundedNaN := raw.value.isNaN || raw.invalid; roundedValid := rawValid
    }
    when(roundedValid && !io.flush) {
        assert(busy && !valid, "common round result belongs to its retained owner")
        response.value := I1FloatingPointFormat.canonical(fNFromRecFN(e, s, roundedValue),
            double, Some(roundedNaN))
        response.flags := roundedFlags
        valid := true.B
    }
    when(io.result.fire) { busy := false.B; valid := false.B }
    when(io.flush) { busy := false.B; valid := false.B; rawValid := false.B }
    assert(PopCount(results.map(_.valid).toSeq) <= 1.U, "one raw FP producer per format")
}
