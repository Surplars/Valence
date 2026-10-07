package soc.core.ooo

import chisel3._
import chisel3.util._

/** Instruction supply metadata before expansion, prediction, or architectural admission. */
class RawFetchInstruction extends Bundle {
    val instruction = UInt(32.W)
    val accessFault = Bool()
    val pageFault = Bool()
    val faultAddress = UInt(64.W)
    val pc = UInt(64.W)
    val nextPc = UInt(64.W)
}

/** Decode's accepted successor; a performance hint, never architectural authorization. */
class RawFetchSuccessor extends Bundle {
    val pc = UInt(64.W)
    val instruction = UInt(32.W)
    val nextPc = UInt(64.W)
}

/** Early alternatives for each possible accepted prefix; only predicts is late. */
class RawFetchValidation extends Bundle {
    val sequentialPc = UInt(64.W)
    val predictedPc = UInt(64.W)
    val predicts = Bool()
}

/** Compact, registered instruction reservoir between the fetch cache and decode.
  *
  * Capacity is two rename packets; minimum latency is one cycle, and both ports
  * sustain renameWidth instructions per cycle. Input credits use registered
  * occupancy only: neither decode acceptance nor a prediction can feed through
  * to the raw fetch payload. Dedicated head slots avoid a pointer-indexed RAM.
  * A partial dequeue compacts the surviving instructions, allowing two-wide
  * admission to join the tail of one fetched packet to the next packet. Each
  * slot records its real PC and supply prediction. Raw JAL/C.J and a small
  * accepted-successor cache steer supply before full decode; taken supply
  * predictions terminate that raw packet. Decode independently validates its
  * own successor against the next queued/offered PC before retaining the path.
  *
  * Input/output lanes are contiguous prefixes. Flush cancels all queued and
  * same-cycle offered instructions, then restarts the supply PC; output validity
  * deliberately does not depend on flush, because a decoded prediction may
  * itself generate that flush. The consumer owns recovery-cycle suppression.
  */
class RegisteredFetchPacket(width: Int, compressed: Boolean, resetPc: BigInt,
    parallelValidation: Boolean = false, hintEntries: Int = 8, splitCursor: Boolean = false) extends Module {
    require(width >= 1 && width <= 4)
    require(resetPc >= 0 && resetPc < (BigInt(1) << 64))
    require(Set(8, 16, 32).contains(hintEntries))
    private val capacity = 2 * width
    private val countBits = log2Ceil(capacity + 1)
    private val offsetBits = log2Ceil(4 * width + 1)
    val io = IO(new Bundle {
        val supply = Input(Vec(width, Valid(new RawFetchInstruction)))
        val pause = Input(Bool())
        val consume = Input(Vec(width, Bool()))
        val flush = Input(Valid(UInt(64.W)))
        val expectedNext = Input(Valid(UInt(64.W)))
        val validation = if (parallelValidation) Some(Input(Vec(width, new RawFetchValidation))) else None
        val train = Input(Vec(width, Valid(new RawFetchSuccessor)))
        val invalidate = Input(Bool())
        val captured = Output(Vec(width, Bool()))
        val instructions = Output(Vec(width, Valid(new RawFetchInstruction)))
        val fetchPc = Output(UInt(64.W))
        val nextFetchPc = Output(UInt(64.W))
        val occupancy = Output(UInt(countBits.W))
    })
    val slots = Reg(Vec(capacity, new RawFetchInstruction))
    val count = RegInit(0.U(countBits.W))
    val rawCursor = RegInit(resetPc.U(64.W))
    // A correction is captured without a late conditional write-enable. The
    // registered selector overrides speculative raw progress on the next cycle,
    // with exactly the old redirect latency. Decode/path validation cannot
    // drive the normal cursor's data or CE. No offered instruction survives a
    // same-cycle correction; the cancelled raw cursor is simply unobservable.
    val correctionPc = if (splitCursor) Some(Reg(UInt(64.W))) else None
    val correctionPending = if (splitCursor) Some(RegInit(false.B)) else None
    val supplyPc = if (splitCursor) Mux(correctionPending.get, correctionPc.get, rawCursor) else rawCursor
    val hintValid = RegInit(VecInit(Seq.fill(hintEntries)(false.B)))
    val hintPc = Reg(Vec(hintEntries, UInt(64.W)))
    val hintInstruction = Reg(Vec(hintEntries, UInt(32.W)))
    val hintNextPc = Reg(Vec(hintEntries, UInt(64.W)))
    val hintAligned = Reg(Vec(hintEntries, Bool()))
    val hintDifferent = Reg(Vec(hintEntries, Bool()))
    private val hintBits = log2Ceil(hintEntries)
    def hintIndex(address: UInt): UInt = address(hintBits, 1) ^ address(2 * hintBits, hintBits + 1)
    for (entry <- 0 until hintEntries) {
        for (lane <- 0 until width) {
            when(io.train(lane).valid && hintIndex(io.train(lane).bits.pc) === entry.U) {
                hintValid(entry) := true.B
                hintPc(entry) := io.train(lane).bits.pc
                hintInstruction(entry) := io.train(lane).bits.instruction
                hintNextPc(entry) := io.train(lane).bits.nextPc
                val trainedShort = compressed.B && io.train(lane).bits.instruction(1, 0) =/= 3.U
                val trainedSuccessor = io.train(lane).bits.pc + Mux(trainedShort, 2.U, 4.U)
                hintAligned(entry) := (if (compressed) !io.train(lane).bits.nextPc(0)
                    else io.train(lane).bits.nextPc(1, 0) === 0.U)
                hintDifferent(entry) := io.train(lane).bits.nextPc =/= trainedSuccessor
            }
        }
        when(io.invalidate) { hintValid(entry) := false.B }
    }
    val capturePrefix = Wire(Vec(width + 1, Bool()))
    val byteOffsets = Wire(Vec(width + 1, UInt(offsetBits.W)))
    val rawPcs = Wire(Vec(width, UInt(64.W)))
    val rawNextPcs = Wire(Vec(width, UInt(64.W)))
    val rawTaken = Wire(Vec(width, Bool()))
    // These carry chains start at the registered supply cursor. Instruction
    // lengths select a completed candidate, not an adder launched by decode.
    // Correction selection is a late control signal. Calculate normal and
    // correction alternatives from their own registers BEFORE that selection,
    // so correctionPending cannot launch low-PC + high-PC carry chains.
    // Modulo-XLEN arithmetic and the original redirect latency are unchanged.
    val cursorBases = if (splitCursor) Seq(rawCursor, correctionPc.get) else Seq(rawCursor)
    val cursorHighs = cursorBases.map(_(63, 21))
    // High-word +/-1 is prepared in parallel eight-bit slices before any hint,
    // jump or correction selection. Preserve packet/redirect latency and the
    // exact 2MiB/XLEN wrap behavior without a six-CARRY8 high-word chain.
    val incrementedHighs = cursorHighs.map(high => TimingArithmetic.neighbor(high))
    val decrementedHighs = cursorHighs.map(high => TimingArithmetic.neighbor(high, decrement = true))
    def selectCursor(values: Seq[UInt]): UInt =
        if (splitCursor) Mux(correctionPending.get, values(1), values(0)) else values.head
    val pcCandidates = (0 to 2 * width).map { offset =>
        val alternatives = cursorBases.indices.map { base =>
            val low = cursorBases(base)(20, 0) +& (2 * offset).U
            Cat(Mux(low(21), incrementedHighs(base), cursorHighs(base)), low(20, 0))
        }
        (2 * offset).U -> selectCursor(alternatives)
    }
    def rawPc(offset: UInt): UInt = MuxLookup(offset, supplyPc)(pcCandidates)
    capturePrefix(0) := !io.pause
    byteOffsets(0) := 0.U
    for (lane <- 0 until width) {
        io.instructions(lane).valid := count > lane.U
        io.instructions(lane).bits := slots(lane)
        capturePrefix(lane + 1) := capturePrefix(lane) && io.supply(lane).valid &&
            count <= (capacity - lane - 1).U &&
            (if (lane == 0) true.B else !rawTaken(lane - 1))
        val instruction = io.supply(lane).bits.instruction
        val short = compressed.B && instruction(1, 0) =/= 3.U
        byteOffsets(lane + 1) := byteOffsets(lane) + Mux(short, 2.U, 4.U)
        rawPcs(lane) := rawPc(byteOffsets(lane))
        val successor = rawPc(byteOffsets(lane + 1))
        // RV64 C.J only (quadrant 1, funct3=101); funct3=001 is C.ADDIW.
        val direct = !short && instruction(6, 0) === "h6f".U
        val compressedJump = short && instruction(1, 0) === 1.U && instruction(15, 13) === 5.U
        val jumpOffset = Cat(instruction(31), instruction(19, 12),
            instruction(20), instruction(30, 21), 0.U(1.W))
        val compressedOffset = Cat(Fill(9, instruction(12)), instruction(12), instruction(8),
            instruction(10, 9), instruction(6), instruction(7), instruction(2), instruction(11),
            instruction(5, 3), 0.U(1.W))
        // Add the lane byte offset to the signed immediate BEFORE launching
        // the cursor addition. No cursor+lane carry chain may feed a second
        // branch carry chain (or a second 43-bit high increment). The 22-bit
        // immediate retains its sign across a 2MiB boundary and RV64 wrap.
        val offset = Mux(compressedJump, compressedOffset, jumpOffset)
        val relativeOffset = Cat(offset(20), offset) + byteOffsets(lane)
        val targets = cursorBases.indices.map { base =>
            val lowSum = cursorBases(base)(20, 0) +& relativeOffset(20, 0)
            val targetHigh = Mux(relativeOffset(21) && !lowSum(21), decrementedHighs(base),
                Mux(!relativeOffset(21) && lowSum(21), incrementedHighs(base), cursorHighs(base)))
            Cat(targetHigh, lowSum(20, 0))
        }
        val directTarget = selectCursor(targets)
        val index = hintIndex(rawPcs(lane))
        val selectedValid = BankedOneHotRead(hintValid, index)
        val selectedPc = BankedOneHotRead(hintPc, index)
        val selectedInstruction = BankedOneHotRead(hintInstruction, index)
        val selectedNextPc = BankedOneHotRead(hintNextPc, index)
        val selectedAligned = BankedOneHotRead(hintAligned, index)
        val selectedDifferent = BankedOneHotRead(hintDifferent, index)
        val hintHit = selectedValid && selectedPc === rawPcs(lane) && selectedInstruction === instruction
        val relative = direct || compressedJump
        val target = Mux(relative, directTarget, selectedNextPc)
        // Modulo-XLEN addition is cancellative: pc+imm != pc+length iff imm !=
        // length, including signed offsets and wrap. Qualify from the immediate
        // and two low bits, never from the late split-adder target. A hint's
        // full-PC/instruction match makes its training-time qualification exact.
        val relativeLow = (rawPcs(lane)(1, 0) + offset(1, 0))(1, 0)
        val relativeAligned = if (compressed) !relativeLow(0) else relativeLow === 0.U
        val relativeDifferent = offset =/= Mux(compressedJump, 2.U(21.W), 4.U(21.W))
        val qualified = Mux(relative, relativeAligned && relativeDifferent,
            hintHit && selectedAligned && selectedDifferent)
        val fault = io.supply(lane).bits.accessFault || io.supply(lane).bits.pageFault
        val priorFault = (0 until lane).map(earlier =>
            io.supply(earlier).bits.accessFault || io.supply(earlier).bits.pageFault)
            .foldLeft(false.B)(_ || _)
        rawTaken(lane) := !fault && !priorFault && qualified
        rawNextPcs(lane) := Mux(rawTaken(lane), target, successor)
        assert(!io.consume(lane) || io.instructions(lane).valid,
            "fetch reservoir cannot consume an empty lane")
        if (lane > 0) {
            assert(!io.consume(lane) || io.consume(lane - 1),
                "fetch reservoir consumption must be a contiguous prefix")
        }
    }
    val consumed = PopCount(io.consume)
    // Raw offers can be observed while a redirect wins. Flush has last state
    // priority, so they cannot occupy a slot or advance the next supply PC.
    val captured = PopCount(capturePrefix.drop(1))
    val remaining = count - consumed
    for (slot <- 0 until capacity) {
        when(consumed =/= 0.U && slot.U < remaining) {
            slots(slot) := MuxLookup(consumed, slots(slot))(
                (1 to width).filter(slot + _ < capacity).map { shift =>
                    shift.U -> slots(slot + shift)
                })
        }
        for (lane <- 0 until width) {
            when(capturePrefix(lane + 1) && remaining + lane.U === slot.U) {
                slots(slot) := io.supply(lane).bits
                slots(slot).pc := rawPcs(lane)
                slots(slot).nextPc := rawNextPcs(lane)
            }
        }
    }
    count := remaining + captured
    // Precompute carry chains from the registered PC. Compressed lengths and
    // capture credits select one candidate instead of launching a late adder.
    val supplySuccessor = MuxLookup(captured, supplyPc)(
        (1 to width).map(lanes => lanes.U -> rawNextPcs(lanes - 1)))
    // Compare the first surviving instruction, not the cursor several words
    // ahead. If no instruction survives, a matching offer or cursor is enough.
    // This keeps an already-correct taken path and discards a stale early hint.
    val queuedSuccessor = MuxLookup(consumed, slots(0).pc)(
        (1 to width).filter(_ < capacity).map(lanes => lanes.U -> slots(lanes).pc))
    val firstSuccessor = Mux(remaining =/= 0.U, queuedSuccessor, supplyPc)
    val mismatch = if (parallelValidation) {
        // Compare registered queue candidates against both early alternatives
        // before PMP/rename selects a prefix. Late admission selects one BIT,
        // rather than a 64-bit successor mux followed by a 64-bit comparator.
        val candidates = (1 to width).map { lanes =>
            val observed = Mux(count > lanes.U, slots(lanes).pc, supplyPc)
            val validation = io.validation.get(lanes - 1)
            consumed === lanes.U && Mux(validation.predicts,
                observed =/= validation.predictedPc, observed =/= validation.sequentialPc)
        }
        candidates.reduce(_ || _) || (consumed === 0.U && firstSuccessor =/= io.expectedNext.bits)
    } else firstSuccessor =/= io.expectedNext.bits
    val wrongPath = io.expectedNext.valid && mismatch
    val cancel = io.flush.valid || wrongPath
    for (lane <- 0 until width) {
        io.captured(lane) := capturePrefix(lane + 1) && !cancel
    }
    io.nextFetchPc := Mux(io.flush.valid, io.flush.bits,
        Mux(wrongPath, io.expectedNext.bits, supplySuccessor))
    if (splitCursor) {
        rawCursor := supplySuccessor
        correctionPc.get := Mux(io.flush.valid, io.flush.bits, io.expectedNext.bits)
        correctionPending.get := cancel
    } else rawCursor := io.nextFetchPc
    when(cancel) {
        count := 0.U
    }
    io.fetchPc := supplyPc
    io.occupancy := count
    assert(count <= capacity.U, "fetch reservoir capacity exceeded")
}
