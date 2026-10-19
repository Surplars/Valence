// Arithmetic/IEEE adapter copied from the local pinned-HardFloat integration; no OoO state/control.
// Provenance: src/main/scala/core/ooo/FloatingPointExecute.scala. Keep numerical changes independently SoftFloat-tested.
package soc.core.inorder

import chisel3._
import chisel3.util._
import hardfloat._

/** Sign/class/move, min/max/compare and conversions. Capacity 1, latency 2, II 3.
  * Unit groups are removed at elaboration, not merely disabled at their inputs.
  * Sign injection and raw moves preserve NaN payloads; computational S inputs
  * perform boxing checks. Only numerical outputs are canonicalized.
  * FP-to-W/WU results both sign-extend on RV64; invalid suppresses inexact.
  */
class I1FloatingPointMisc(p: FiveStageConfig, double: Boolean, c: I1FloatingPointConfig) extends Module {
    val io = IO(new I1FloatingPointProducerIO(p))
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val w = e + s
    override def desiredName: String = s"I1FloatingPointMisc${if (double) "D" else "S"}"
    val idle :: capture :: normalizeInteger :: prepared :: convertWait :: finished :: integerFinish :: Nil = Enum(7)
    val state = RegInit(idle)
    val finishedOwner = if (p.fpgaTimingCuts) Some(RegInit(false.B)) else None
    val response = Reg(new I1FloatingPointResult(p))
    val input = Reg(new I1FloatingPointExecution(p))
    val inst = input.command.instruction
    val narrowCuts = p.fpgaTimingCuts && !double && c.d && c.conversions
    val convertStart = WireDefault(false.B)
    val convertReady = WireDefault(true.B)
    val a = Reg(UInt(w.W))
    val b = Reg(UInt(w.W))
    val recA = Reg(UInt((w + 1).W))
    val recB = Reg(UInt((w + 1).W))
    // Capture boxing/recoding and the complete owner before comparisons or
    // conversion rounding. Raw FMV inputs remain separate from numerical a/b.
    when(io.request.fire) { input := io.request.bits }
    val intake = if (p.fpgaTimingCuts) input else io.request.bits
    val prepareInput = if (p.fpgaTimingCuts) state === capture && !io.flush else io.request.fire
    when(prepareInput) {
        val left = I1FloatingPointFormat.operand(intake.operands(0), double)
        val right = I1FloatingPointFormat.operand(intake.operands(1), double)
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
        choose(I1FloatingPointDecode.sign(inst), if (double) injected else I1FloatingPointBits.boxSingle(injected))
        choose(I1FloatingPointDecode.classify(inst), classifyRecFN(e, s, recA))
        choose(I1FloatingPointDecode.moveToFloat(inst), if (double) input.command.integerSource
            else I1FloatingPointBits.boxSingle(input.command.integerSource))
        val raw = input.operands(0)
        choose(I1FloatingPointDecode.moveToInteger(inst), if (double) raw else Cat(Fill(32, raw(31)), raw(31, 0)))
    }
    if (c.compareMinMax) {
        val signaling = I1FloatingPointDecode.compare(inst) && inst(14, 12) =/= 2.U
        val (less, same, greater, exceptions, aNaN, bNaN, bothZero) = if (p.fpgaTimingCuts) {
            // IEEE interchange magnitudes are monotonic for non-NaNs,
            // including subnormals/infinities. Capture their comparison
            // and classifications at the EXISTING capture edge, before
            // min/max selects a wide result in prepared. No extra FP cycle.
            // Keep raw moves/sign injection and HardFloat rounding unchanged.
            val left = I1FloatingPointFormat.operand(intake.operands(0), double)
            val right = I1FloatingPointFormat.operand(intake.operands(1), double)
            def nan(x: UInt): Bool = x(w - 2, s - 1).andR && x(s - 2, 0).orR
            val facts = Reg(Vec(9, Bool()))
            when(prepareInput) {
                facts := VecInit(Seq(left(w - 2, 0) < right(w - 2, 0),
                    I1TimingMath.equal(left(w - 2, 0), right(w - 2, 0)), left(w - 1), right(w - 1),
                    !left(w - 2, 0).orR && !right(w - 2, 0).orR,
                    nan(left), nan(right), nan(left) && !left(s - 2), nan(right) && !right(s - 2)))
            }
            val Seq(magnitudeLess, magnitudeEqual, negativeA, negativeB, zeros,
                nanA, nanB, signalingA, signalingB) = facts.toSeq
            val ordered = !nanA && !nanB
            val orderedLess = !zeros && ((negativeA && !negativeB) ||
                ((negativeA === negativeB) &&
                    Mux(negativeA, !magnitudeLess && !magnitudeEqual, magnitudeLess)))
            val orderedEqual = zeros || ((negativeA === negativeB) && magnitudeEqual)
            val invalid = signalingA || signalingB || (signaling && !ordered)
            (ordered && orderedLess, ordered && orderedEqual, ordered && !orderedLess && !orderedEqual,
                Cat(invalid, 0.U(4.W)), nanA, nanB, zeros)
        } else {
            val compare = Module(new CompareRecFN(e, s))
            compare.io.a := recA; compare.io.b := recB; compare.io.signaling := signaling
            (compare.io.lt, compare.io.eq, compare.io.gt, compare.io.exceptionFlags,
                a(w - 2, s - 1).andR && a(s - 2, 0).orR,
                b(w - 2, s - 1).andR && b(s - 2, 0).orR,
                a(w - 2, 0) === 0.U && b(w - 2, 0) === 0.U)
        }
        choose(I1FloatingPointDecode.compare(inst), MuxLookup(inst(14, 12), 0.U(64.W))(Seq(
                0.U -> Mux(less || same, 1.U(64.W), 0.U(64.W)),
                1.U -> Mux(less, 1.U(64.W), 0.U(64.W)),
                2.U -> Mux(same, 1.U(64.W), 0.U(64.W)))), exceptions)
        val maximum = inst(12)
        val takeA = Mux(same, !bothZero || Mux(maximum, !a(w - 1), a(w - 1)),
            Mux(maximum, greater, less))
        val selected = Mux(aNaN, b, Mux(bNaN, a, Mux(takeA, a, b)))
        choose(I1FloatingPointDecode.minMax(inst), I1FloatingPointFormat.canonical(selected, double, Some(aNaN && bNaN)),
            exceptions) // quiet min/max: only sNaN raises NV
    }
    if (c.conversions) {
        val unsigned = inst(20)
        val long = inst(21)
        val offeredInst = intake.command.instruction
        val offeredInteger = intake.command.integerSource
        val normalizedInteger = Mux(offeredInst(21), offeredInteger, Mux(offeredInst(20),
            offeredInteger(31, 0).pad(64), Cat(Fill(32, offeredInteger(31)), offeredInteger(31, 0))))
        val magnitude = if (p.fpgaTimingCuts) Some(Reg(UInt(64.W))) else None
        val negative = if (p.fpgaTimingCuts) Some(Reg(Bool())) else None
        val sign = !offeredInst(20) && normalizedInteger(63)
        when(prepareInput) {
            magnitude.foreach(_ := Mux(sign, -normalizedInteger, normalizedInteger))
            negative.foreach(_ := sign)
        }
        // Exactly the pinned signed integer -> absolute magnitude identity.
        // Register the negation BEFORE leading-zero count and barrel alignment.
        val integerRaw = rawFloatFromIN(if (p.fpgaTimingCuts) false.B else !offeredInst(20),
            magnitude.getOrElse(normalizedInteger))
        if (p.fpgaTimingCuts) integerRaw.sign := negative.get
        val integerPrepared = Reg(chiselTypeOf(integerRaw))
        when(if (p.fpgaTimingCuts) state === normalizeInteger && !io.flush else io.request.fire) {
            integerPrepared := integerRaw
        }
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
        choose(I1FloatingPointDecode.fromInteger(inst), if (double) ieee else I1FloatingPointBits.boxSingle(ieee),
            fromInt.io.exceptionFlags)
        def toInteger(width: Int): (UInt, UInt) = {
            if (p.fpgaTimingCuts) {
                val unit = Module(new I1FloatingPointToIntegerCuts(e, s, width))
                unit.io.in := recA; unit.io.signedOut := !unsigned
                unit.io.roundingMode := input.rounding
                unit.io.capture := state === prepared && !io.flush
                (unit.io.out, unit.io.intExceptionFlags)
            } else {
                val unit = Module(new RecFNToIN(e, s, width))
                unit.io.in := recA; unit.io.signedOut := !unsigned
                unit.io.roundingMode := input.rounding
                (unit.io.out, unit.io.intExceptionFlags)
            }
        }
        val (to32, flags32) = toInteger(32)
        val (to64, flags64) = toInteger(64)
        val intFlags = Mux(long, flags64, flags32)
        val integerValue = Mux(long, to64, Cat(Fill(32, to32(31)), to32))
        val integerFlags = Cat(intFlags(2) || intFlags(1), 0.U(3.W), intFlags(0))
        choose(I1FloatingPointDecode.toInteger(inst), integerValue, integerFlags)
        if (c.d) {
            val inE = if (double) 8 else 11
            val inS = if (double) 24 else 53
            val source = if (double) I1FloatingPointBits.operand(intake.operands(0), true.B)(31, 0)
                else intake.operands(0)
            val sourceRaw = rawFloatFromRecFN(inE, inS, recFNFromFN(inE, inS, source))
            val conversionPrepared = Reg(chiselTypeOf(sourceRaw))
            when(prepareInput) { conversionPrepared := sourceRaw }
            // F <-> D have different exponent widths, so both take the pinned
            // general RecFNToRecFN raw-input/rounding path, with a timing cut.
            if (narrowCuts) {
                val convert = Module(new I1FloatingPointNarrowRoundCuts)
                convert.io.flush := io.flush
                convert.io.start.valid := convertStart; convert.io.start.bits := conversionPrepared
                convert.io.invalid := isSigNaNRawFloat(conversionPrepared); convert.io.rounding := input.rounding
                convertReady := convert.io.result.valid
                choose(I1FloatingPointDecode.convert(inst),
                    I1FloatingPointFormat.canonical(fNFromRecFN(e, s, convert.io.result.bits.value),
                        false, Some(convert.io.result.bits.nan)), convert.io.result.bits.flags)
            } else {
                val convert = Module(new RoundAnyRawFNToRecFN(inE, inS, e, s,
                    hardfloat.consts.flRoundOpt_sigMSBitAlwaysZero))
                convert.io.in := conversionPrepared
                convert.io.invalidExc := isSigNaNRawFloat(conversionPrepared)
                convert.io.infiniteExc := false.B
                // Exact widening still checks rm/frm legality in the dispatcher.
                convert.io.roundingMode := (if (double) 0.U else input.rounding)
                convert.io.detectTininess := true.B
                choose(I1FloatingPointDecode.convert(inst),
                    I1FloatingPointFormat.canonical(fNFromRecFN(e, s, convert.io.out),
                        double, Some(conversionPrepared.isNaN)), convert.io.exceptionFlags)
            }
        }
    }
    val kind = (c.signClassMove.B && (I1FloatingPointDecode.sign(inst) || I1FloatingPointDecode.classify(inst) ||
        I1FloatingPointDecode.moveToFloat(inst) || I1FloatingPointDecode.moveToInteger(inst))) ||
        (c.compareMinMax.B && (I1FloatingPointDecode.compare(inst) || I1FloatingPointDecode.minMax(inst))) ||
        (c.conversions.B && (I1FloatingPointDecode.toInteger(inst) || I1FloatingPointDecode.fromInteger(inst) ||
            (c.d.B && I1FloatingPointDecode.convert(inst))))
    val legal = I1FloatingPointDecode.supported(inst, c) && kind &&
        inst(25) === double.B &&
        (!I1FloatingPointDecode.usesRounding(inst) || input.rounding <= 4.U)
    val deferConvert = narrowCuts.B && legal && I1FloatingPointDecode.convert(inst)
    val deferInteger = p.fpgaTimingCuts.B && legal && c.conversions.B &&
        I1FloatingPointDecode.toInteger(inst)
    convertStart := state === prepared && deferConvert && !io.flush
    val qualified = choices.map { case (select, data, exceptions) =>
        (if (p.fpgaTimingCuts) select && legal else select, data, exceptions)
    }
    val value = Mux1H(qualified.map { case (select, data, _) => select -> data }.toSeq)
    val flags = Mux1H(qualified.map { case (select, _, exceptions) => select -> exceptions }.toSeq)
    when(state === prepared && legal && !io.flush) {
        assert(PopCount(choices.map(_._1).toSeq) === 1.U, "every legal miscellaneous FP instruction selects one result")
    }
    io.request.ready := state === idle && !io.flush
    io.completed := finishedOwner.getOrElse(state === finished)
    io.result.valid := io.completed && !io.flush
    io.result.bits := response
    when(io.request.fire) {
        finishedOwner.foreach(_ := false.B)
        state := (if (p.fpgaTimingCuts) capture else prepared)
        // All payload/status fields are written at real completion. Clearing
        // an invalid value here routed branch recovery through request.fire
        // to 64 payload-reset pins. Only token ownership is needed at intake.
        if (!p.fpgaTimingCuts) { response := 0.U.asTypeOf(new I1FloatingPointResult(p)) }
        response.token := io.request.bits.command.token
    }
    if (p.fpgaTimingCuts) {
        when(state === capture && !io.flush) {
            state := Mux(I1FloatingPointDecode.fromInteger(inst), normalizeInteger, prepared)
        }
        when(state === normalizeInteger && !io.flush) { state := prepared }
    }
    when(state === prepared && deferConvert) { state := convertWait }
    when(state === prepared && deferInteger) { state := integerFinish }
    when((state === prepared && !deferConvert && !deferInteger) ||
        (state === convertWait && convertReady) || state === integerFinish) {
        state := finished
        finishedOwner.foreach(_ := true.B)
        response.value := (if (p.fpgaTimingCuts) value else Mux(legal, value, 0.U))
        response.flags := (if (p.fpgaTimingCuts) flags else Mux(legal, flags, 0.U))
        response.exception := !legal; response.cause := Mux(legal, 0.U, 2.U)
        response.tval := Mux(legal, 0.U, inst.pad(64))
    }
    when(io.result.fire || io.flush) { state := idle; finishedOwner.foreach(_ := false.B) }
    if (p.fpgaTimingCuts) when(!reset.asBool) {
        assert(finishedOwner.get === (state === finished), "FP completion phase predecode changed owner timing")
    }
}

/** Single-outstanding numerical dispatcher. IEEE boundary, exact-token response.
  * Unsupported/pruned/reserved encodings return an illegal instruction, never hang.
  * Latency is the selected producer's latency; no same-cycle refill on completion.
  * Timing cuts add one registered dispatch edge, not another transaction slot.
  */
class I1FloatingPointExecute(p: FiveStageConfig, c: I1FloatingPointConfig) extends Module {
    require(c.f)
    val io = IO(new I1FloatingPointProducerIO(p))
    val busy = RegInit(false.B)
    val rejected = RegInit(false.B)
    val rejection = Reg(new I1FloatingPointResult(p))
    val dispatch = if (p.fpgaTimingCuts) Some(RegInit(false.B)) else None
    val captured = if (p.fpgaTimingCuts) Some(Reg(chiselTypeOf(io.request.bits))) else None
    // Named pure enable allows the isolated FPGA exporter to bound physical
    // fanout. This is still exactly !busy, not a new owner or capture edge.
    val capturePayloadEnable = WireDefault(!busy)
    captured.foreach { payload =>
        // Unowned payload preparation is not request acceptance. The real
        // fire below alone commits busy/dispatch. Recovery/address legality
        // therefore cannot drive every operand register's clock enable.
        when(capturePayloadEnable) { payload := io.request.bits }
    }
    val intake = captured.getOrElse(io.request.bits)
    val offer = dispatch.getOrElse(io.request.valid && !busy)
    // Existing registered dispatch provides the drain edge: cancel the
    // architectural owner immediately, then clear only local producer state
    // on the following edge. A new request may still enter the capture slot
    // during that clear and dispatch normally one cycle later.
    val cancelPending = if (p.fpgaTimingCuts) Some(RegNext(io.flush, false.B)) else None
    val producerFlush = cancelPending.getOrElse(io.flush)
    val inst = intake.command.instruction
    val legal = I1FloatingPointDecode.supported(inst, c) && !I1FloatingPointDecode.memory(inst) &&
        (!I1FloatingPointDecode.usesRounding(inst) || intake.rounding <= 4.U)
    val producers = scala.collection.mutable.ArrayBuffer.empty[(Bool, I1FloatingPointProducerIO)]
    for (double <- (if (c.d) Seq(false, true) else Seq(false))) {
        val format = inst(25) === double.B
        def connect(select: Bool, unit: I1FloatingPointProducerIO): Unit = {
            producers += ((format && select, unit))
            unit.flush := producerFlush
            unit.request.bits := intake
            unit.request.bits.rounding := Mux(I1FloatingPointDecode.usesRounding(inst), intake.rounding, 0.U)
            // A dispatch already owned before a same-cycle cancellation may
            // start pure arithmetic, but producerFlush kills it before any
            // result can escape. No live branch recovery fans into its data CE.
            unit.request.valid := offer && legal && format && select && !producerFlush
        }
        if (c.resources.sharedFormatRounders) {
            if (c.addSubtract || c.multiply || c.fusedMultiplyAdd || c.divide || c.squareRoot) {
                val prepared = p.fpgaTimingCuts
                val arithmetic = Module(new I1FloatingPointSharedArithmetic(p, double, c, prepared))
                arithmetic.normalization.foreach { input =>
                    val s = if (double) 53 else 24
                    val distances = Reg(Vec(3, UInt(log2Ceil(s).W)))
                    when(capturePayloadEnable) {
                        for (lane <- 0 until 3) {
                            val ieee = I1FloatingPointFormat.operand(io.request.bits.operands(lane), double)
                            distances(lane) := countLeadingZeros(ieee(s - 2, 0))
                        }
                    }
                    input := distances
                }
                connect(
                (c.addSubtract.B && I1FloatingPointDecode.add(inst)) ||
                (c.multiply.B && I1FloatingPointDecode.multiply(inst)) ||
                (c.fusedMultiplyAdd.B && I1FloatingPointDecode.fused(inst)) ||
                (c.divide.B && I1FloatingPointDecode.divide(inst)) ||
                (c.squareRoot.B && I1FloatingPointDecode.sqrt(inst)),
                arithmetic.io)
            }
        } else {
            if (c.addSubtract) connect(I1FloatingPointDecode.add(inst), Module(new I1FloatingPointArithmetic(p, double, "add")).io)
            if (c.multiply) connect(I1FloatingPointDecode.multiply(inst), Module(new I1FloatingPointArithmetic(p, double, "multiply")).io)
            if (c.fusedMultiplyAdd) connect(I1FloatingPointDecode.fused(inst), Module(new I1FloatingPointArithmetic(p, double, "fused")).io)
            if (c.divide || c.squareRoot) connect(
                (c.divide.B && I1FloatingPointDecode.divide(inst)) || (c.squareRoot.B && I1FloatingPointDecode.sqrt(inst)),
                Module(new I1FloatingPointDivSqrt(p, double, c.divide, c.squareRoot)).io)
        }
        if (c.compareMinMax || c.signClassMove || c.conversions) connect(
            I1FloatingPointDecode.sign(inst) || I1FloatingPointDecode.classify(inst) ||
            I1FloatingPointDecode.moveToFloat(inst) || I1FloatingPointDecode.moveToInteger(inst) ||
            I1FloatingPointDecode.minMax(inst) || I1FloatingPointDecode.compare(inst) ||
            I1FloatingPointDecode.toInteger(inst) || I1FloatingPointDecode.fromInteger(inst) || I1FloatingPointDecode.convert(inst),
            Module(new I1FloatingPointMisc(p, double, c)).io)
    }
    val selectedReady = producers.map { case (select, unit) => select && unit.request.ready }.foldLeft(false.B)(_ || _)
    io.request.ready := !busy && !io.flush && (if (p.fpgaTimingCuts) true.B else !legal || selectedReady)
    val results = producers.map(_._2.result)
    val completed = producers.map(_._2.completed)
    io.completed := !cancelPending.getOrElse(false.B) &&
        (rejected || completed.foldLeft(false.B)(_ || _))
    io.result.valid := !io.flush && io.completed
    // At most one producer/rejection owns this transaction. Parallel one-hot
    // payload selection removes the format/unit ordered priority chain.
    io.result.bits := Mux1H((Seq(rejected -> rejection) ++ results.zip(completed).map {
        case (port, owned) => (if (p.fpgaTimingCuts) owned else port.valid) -> port.bits
    }).toSeq)
    // Reuse the existing rejection payload register as an elastic completion
    // holder. Producers retire locally; CPU branch/DT/EX READY cannot reach
    // their state resets. Bypass preserves visible completion latency, while
    // busy still forbids a second owner. No FP queue/slot/payload is added.
    for (port <- results) {
        port.ready := (if (p.fpgaTimingCuts) busy && !rejected && !producerFlush
            else io.result.ready && !rejected && !io.flush)
    }
    if (p.fpgaTimingCuts) {
        val completing = completed.foldLeft(false.B)(_ || _)
        when(busy && !rejected && completing && !producerFlush && !io.flush && !io.result.fire) {
            rejection := Mux1H(results.zip(completed).map { case (port, owned) => owned -> port.bits }.toSeq)
            rejected := true.B
        }
    }
    val rejectionPayload = WireDefault(0.U.asTypeOf(new I1FloatingPointResult(p)))
    rejectionPayload.token := intake.command.token
    rejectionPayload.exception := true.B
    rejectionPayload.cause := 2.U
    rejectionPayload.tval := inst.pad(64)
    if (p.fpgaTimingCuts) when(offer) { rejection := rejectionPayload }
    def reject(): Unit = {
        rejected := true.B
        if (!p.fpgaTimingCuts) { rejection := rejectionPayload }
    }
    when(io.request.fire) {
        busy := true.B
        dispatch.foreach(_ := true.B)
        if (!p.fpgaTimingCuts) { when(!legal) { reject() } }
    }
    dispatch.foreach { pending =>
        when(pending && !io.flush) {
            when(!legal) { reject(); pending := false.B }
                .elsewhen(selectedReady) { pending := false.B }
        }
    }
    when(io.result.fire) { busy := false.B; rejected := false.B }
    when(io.flush) { busy := false.B; rejected := false.B; dispatch.foreach(_ := false.B) }
    assert(PopCount(Seq(rejected) ++ results.map(_.valid)) <= 1.U, "one outstanding numerical FP producer")
    assert(PopCount(Seq(rejected) ++ completed) <= 1.U, "one registered numerical completion owner")
    when(offer && legal && !io.flush) {
        assert(PopCount(producers.map(_._1).toSeq) === 1.U, "every legal arithmetic encoding has one producer")
    }
}
