package soc.core.ooo

import chisel3._
import chisel3.util._
import hardfloat._

/** Sign/class/move, min/max/compare and conversions. Capacity 1, latency 2, II 3.
  * Unit groups are removed at elaboration, not merely disabled at their inputs.
  * Sign injection and raw moves preserve NaN payloads; computational S inputs
  * perform boxing checks. Only numerical outputs are canonicalized.
  * FP-to-W/WU results both sign-extend on RV64; invalid suppresses inexact.
  */
class FloatingPointMisc(p: OooParams, double: Boolean, c: FloatingPointConfig) extends Module {
    val io = IO(new FloatingPointProducerIO(p))
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val w = e + s
    override def desiredName: String = s"FloatingPointMisc${if (double) "D" else "S"}"
    val idle :: prepared :: finished :: Nil = Enum(3)
    val state = RegInit(idle)
    val response = Reg(new FloatingPointResult(p))
    val input = Reg(new FloatingPointExecution(p))
    val inst = input.command.instruction
    val a = Reg(UInt(w.W))
    val b = Reg(UInt(w.W))
    val recA = Reg(UInt((w + 1).W))
    val recB = Reg(UInt((w + 1).W))
    // Capture boxing/recoding and the complete owner before comparisons or
    // conversion rounding. Raw FMV inputs remain separate from numerical a/b.
    when(io.request.fire) {
        input := io.request.bits
        val left = FloatingPointFormat.operand(io.request.bits.operands(0), double)
        val right = FloatingPointFormat.operand(io.request.bits.operands(1), double)
        a := left; b := right
        recA := recFNFromFN(e, s, left); recB := recFNFromFN(e, s, right)
    }
    // Decode mutually exclusive result kinds in parallel. Do not serialize
    // sign/move/class/compare/conversion data through a last-wins priority mux.
    val choices = scala.collection.mutable.ArrayBuffer.empty[(Bool, UInt, UInt)]
    def choose(kind: Bool, data: UInt, exceptions: UInt = 0.U(5.W)): Unit =
        choices += ((kind, data.pad(64), exceptions))
    if (c.signClassMove) {
        val sign = MuxLookup(inst(14, 12), b(w - 1))(Seq(
            1.U -> !b(w - 1), 2.U -> (a(w - 1) ^ b(w - 1))))
        val injected = Cat(sign, a(w - 2, 0))
        choose(FloatingPointDecode.sign(inst), if (double) injected else FloatingPointBits.boxSingle(injected))
        choose(FloatingPointDecode.classify(inst), classifyRecFN(e, s, recA))
        choose(FloatingPointDecode.moveToFloat(inst), if (double) input.command.integerSource
            else FloatingPointBits.boxSingle(input.command.integerSource))
        val raw = input.operands(0)
        choose(FloatingPointDecode.moveToInteger(inst), if (double) raw else Cat(Fill(32, raw(31)), raw(31, 0)))
    }
    if (c.compareMinMax) {
        val compare = Module(new CompareRecFN(e, s))
        compare.io.a := recA; compare.io.b := recB
        compare.io.signaling := FloatingPointDecode.compare(inst) && inst(14, 12) =/= 2.U
        choose(FloatingPointDecode.compare(inst), MuxLookup(inst(14, 12), 0.U(64.W))(Seq(
                0.U -> Mux(compare.io.lt || compare.io.eq, 1.U(64.W), 0.U(64.W)),
                1.U -> Mux(compare.io.lt, 1.U(64.W), 0.U(64.W)),
                2.U -> Mux(compare.io.eq, 1.U(64.W), 0.U(64.W)))), compare.io.exceptionFlags)
        val aNaN = a(w - 2, s - 1).andR && a(s - 2, 0).orR
        val bNaN = b(w - 2, s - 1).andR && b(s - 2, 0).orR
        val bothZero = a(w - 2, 0) === 0.U && b(w - 2, 0) === 0.U
        val maximum = inst(12)
        val takeA = Mux(compare.io.eq, !bothZero || Mux(maximum, !a(w - 1), a(w - 1)),
            Mux(maximum, compare.io.gt, compare.io.lt))
        val selected = Mux(aNaN, b, Mux(bNaN, a, Mux(takeA, a, b)))
        choose(FloatingPointDecode.minMax(inst), FloatingPointFormat.canonical(selected, double, Some(aNaN && bNaN)),
            compare.io.exceptionFlags) // quiet min/max: only sNaN raises NV
    }
    if (c.conversions) {
        val unsigned = inst(20)
        val long = inst(21)
        val offeredInst = io.request.bits.command.instruction
        val offeredInteger = io.request.bits.command.integerSource
        val normalizedInteger = Mux(offeredInst(21), offeredInteger, Mux(offeredInst(20),
            offeredInteger(31, 0).pad(64), Cat(Fill(32, offeredInteger(31)), offeredInteger(31, 0))))
        val integerRaw = rawFloatFromIN(!offeredInst(20), normalizedInteger)
        val integerPrepared = Reg(chiselTypeOf(integerRaw))
        when(io.request.fire) { integerPrepared := integerRaw }
        // The pinned INToRecFN contract is rawFloatFromIN -> RoundAnyRawFN.
        // Compose those public HardFloat blocks with a register between them;
        // do not modify the vendored implementation or invent new IEEE rules.
        val fromInt = Module(new RoundAnyRawFNToRecFN(integerRaw.expWidth, 64, e, s,
            hardfloat.consts.flRoundOpt_sigMSBitAlwaysZero | hardfloat.consts.flRoundOpt_neverUnderflows))
        fromInt.io.in := integerPrepared
        fromInt.io.invalidExc := false.B; fromInt.io.infiniteExc := false.B
        fromInt.io.roundingMode := input.rounding; fromInt.io.detectTininess := true.B
        // Every integer input is finite: this conversion cannot create NaN.
        val ieee = fNFromRecFN(e, s, fromInt.io.out)
        choose(FloatingPointDecode.fromInteger(inst), if (double) ieee else FloatingPointBits.boxSingle(ieee),
            fromInt.io.exceptionFlags)
        val to32 = Module(new RecFNToIN(e, s, 32))
        val to64 = Module(new RecFNToIN(e, s, 64))
        for (unit <- Seq(to32, to64)) {
            unit.io.in := recA; unit.io.signedOut := !unsigned
            unit.io.roundingMode := input.rounding
        }
        val intFlags = Mux(long, to64.io.intExceptionFlags, to32.io.intExceptionFlags)
        choose(FloatingPointDecode.toInteger(inst), Mux(long, to64.io.out, Cat(Fill(32, to32.io.out(31)), to32.io.out)),
            Cat(intFlags(2) || intFlags(1), 0.U(3.W), intFlags(0)))
        if (c.d) {
            val inE = if (double) 8 else 11
            val inS = if (double) 24 else 53
            val source = if (double) FloatingPointBits.operand(io.request.bits.operands(0), true.B)(31, 0)
                else io.request.bits.operands(0)
            val sourceRaw = rawFloatFromRecFN(inE, inS, recFNFromFN(inE, inS, source))
            val conversionPrepared = Reg(chiselTypeOf(sourceRaw))
            when(io.request.fire) { conversionPrepared := sourceRaw }
            // F <-> D have different exponent widths, so both take the pinned
            // general RecFNToRecFN raw-input/rounding path, with a timing cut.
            val convert = Module(new RoundAnyRawFNToRecFN(inE, inS, e, s,
                hardfloat.consts.flRoundOpt_sigMSBitAlwaysZero))
            convert.io.in := conversionPrepared
            convert.io.invalidExc := isSigNaNRawFloat(conversionPrepared)
            convert.io.infiniteExc := false.B
            // Exact widening has no numerical rounding, but the dispatcher/state
            // still checks rm/frm legality as required by the pinned F spec.
            convert.io.roundingMode := (if (double) 0.U else input.rounding)
            convert.io.detectTininess := true.B
            choose(FloatingPointDecode.convert(inst), FloatingPointFormat.canonical(fNFromRecFN(e, s, convert.io.out),
                double, Some(conversionPrepared.isNaN)), convert.io.exceptionFlags)
        }
    }
    val kind = (c.signClassMove.B && (FloatingPointDecode.sign(inst) || FloatingPointDecode.classify(inst) ||
        FloatingPointDecode.moveToFloat(inst) || FloatingPointDecode.moveToInteger(inst))) ||
        (c.compareMinMax.B && (FloatingPointDecode.compare(inst) || FloatingPointDecode.minMax(inst))) ||
        (c.conversions.B && (FloatingPointDecode.toInteger(inst) || FloatingPointDecode.fromInteger(inst) ||
            (c.d.B && FloatingPointDecode.convert(inst))))
    val legal = FloatingPointDecode.supported(inst, c) && kind &&
        inst(25) === double.B &&
        (!FloatingPointDecode.usesRounding(inst) || input.rounding <= 4.U)
    val value = Mux1H(choices.map { case (select, data, _) => select -> data }.toSeq)
    val flags = Mux1H(choices.map { case (select, _, exceptions) => select -> exceptions }.toSeq)
    when(state === prepared && legal && !io.flush) {
        assert(PopCount(choices.map(_._1).toSeq) === 1.U, "every legal miscellaneous FP instruction selects one result")
    }
    io.request.ready := state === idle && !io.flush
    io.result.valid := state === finished && !io.flush
    io.result.bits := response
    when(io.request.fire) {
        state := prepared
        response := 0.U.asTypeOf(new FloatingPointResult(p))
        response.token := io.request.bits.command.token
    }
    when(state === prepared) {
        state := finished
        response.value := Mux(legal, value, 0.U); response.flags := Mux(legal, flags, 0.U)
        response.exception := !legal; response.cause := Mux(legal, 0.U, 2.U)
        response.tval := Mux(legal, 0.U, inst.pad(64))
    }
    when(io.result.fire || io.flush) { state := idle }
}

/** Single-outstanding numerical dispatcher. IEEE boundary, exact-token response.
  * Unsupported/pruned/reserved encodings return an illegal instruction, never hang.
  * Latency is the selected producer's latency; no same-cycle refill on completion.
  */
class FloatingPointExecute(p: OooParams, c: FloatingPointConfig) extends Module {
    require(c.f)
    val io = IO(new FloatingPointProducerIO(p))
    val busy = RegInit(false.B)
    val rejected = RegInit(false.B)
    val rejection = Reg(new FloatingPointResult(p))
    val inst = io.request.bits.command.instruction
    val legal = FloatingPointDecode.supported(inst, c) && !FloatingPointDecode.memory(inst) &&
        (!FloatingPointDecode.usesRounding(inst) || io.request.bits.rounding <= 4.U)
    val producers = scala.collection.mutable.ArrayBuffer.empty[(Bool, FloatingPointProducerIO)]
    for (double <- (if (c.d) Seq(false, true) else Seq(false))) {
        val format = inst(25) === double.B
        def connect(select: Bool, unit: FloatingPointProducerIO): Unit = {
            producers += ((format && select, unit))
            unit.flush := io.flush
            unit.request.bits := io.request.bits
            unit.request.bits.rounding := Mux(FloatingPointDecode.usesRounding(inst), io.request.bits.rounding, 0.U)
            unit.request.valid := io.request.valid && !busy && legal && format && select && !io.flush
        }
        if (c.resources.sharedFormatRounders) {
            if (c.addSubtract || c.multiply || c.fusedMultiplyAdd || c.divide || c.squareRoot) connect(
                (c.addSubtract.B && FloatingPointDecode.add(inst)) ||
                (c.multiply.B && FloatingPointDecode.multiply(inst)) ||
                (c.fusedMultiplyAdd.B && FloatingPointDecode.fused(inst)) ||
                (c.divide.B && FloatingPointDecode.divide(inst)) ||
                (c.squareRoot.B && FloatingPointDecode.sqrt(inst)),
                Module(new FloatingPointSharedArithmetic(p, double, c)).io)
        } else {
            if (c.addSubtract) connect(FloatingPointDecode.add(inst), Module(new FloatingPointArithmetic(p, double, "add")).io)
            if (c.multiply) connect(FloatingPointDecode.multiply(inst), Module(new FloatingPointArithmetic(p, double, "multiply")).io)
            if (c.fusedMultiplyAdd) connect(FloatingPointDecode.fused(inst), Module(new FloatingPointArithmetic(p, double, "fused")).io)
            if (c.divide || c.squareRoot) connect(
                (c.divide.B && FloatingPointDecode.divide(inst)) || (c.squareRoot.B && FloatingPointDecode.sqrt(inst)),
                Module(new FloatingPointDivSqrt(p, double, c.divide, c.squareRoot)).io)
        }
        if (c.compareMinMax || c.signClassMove || c.conversions) connect(
            FloatingPointDecode.sign(inst) || FloatingPointDecode.classify(inst) ||
            FloatingPointDecode.moveToFloat(inst) || FloatingPointDecode.moveToInteger(inst) ||
            FloatingPointDecode.minMax(inst) || FloatingPointDecode.compare(inst) ||
            FloatingPointDecode.toInteger(inst) || FloatingPointDecode.fromInteger(inst) || FloatingPointDecode.convert(inst),
            Module(new FloatingPointMisc(p, double, c)).io)
    }
    val selectedReady = producers.map { case (select, unit) => select && unit.request.ready }.foldLeft(false.B)(_ || _)
    io.request.ready := !busy && !io.flush && (!legal || selectedReady)
    val results = producers.map(_._2.result)
    io.result.valid := !io.flush && (rejected || results.map(_.valid).foldLeft(false.B)(_ || _))
    // At most one producer/rejection owns this transaction. Parallel one-hot
    // payload selection removes the format/unit ordered priority chain.
    io.result.bits := Mux1H((Seq(rejected -> rejection) ++ results.map(port => port.valid -> port.bits)).toSeq)
    for (port <- results) {
        port.ready := io.result.ready && !rejected && !io.flush
    }
    when(io.request.fire) {
        busy := true.B
        when(!legal) {
            rejected := true.B
            rejection := 0.U.asTypeOf(new FloatingPointResult(p))
            rejection.token := io.request.bits.command.token
            rejection.exception := true.B; rejection.cause := 2.U; rejection.tval := inst.pad(64)
        }
    }
    when(io.result.fire) { busy := false.B; rejected := false.B }
    when(io.flush) { busy := false.B; rejected := false.B }
    assert(PopCount(Seq(rejected) ++ results.map(_.valid)) <= 1.U, "one outstanding numerical FP producer")
    when(io.request.valid && legal && !busy && !io.flush) {
        assert(PopCount(producers.map(_._1).toSeq) === 1.U, "every legal arithmetic encoding has one producer")
    }
}
