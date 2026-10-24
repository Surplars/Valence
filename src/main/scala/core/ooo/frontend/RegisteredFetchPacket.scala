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

/** A-phase metadata, before length-selected PMP and raw successor prediction. */
class FetchPhaseInput(width: Int) extends Bundle {
    val faultOffsets = Vec(width, UInt(5.W))
    val denied = Vec(2 * width, Bool())
}

/** One compact aligned token. Presence is held separately as resettable state. */
class FetchPhaseToken(width: Int) extends Bundle {
    val pc = UInt(64.W)
    val instructions = Vec(width, UInt(32.W))
    val accessFaults = Vec(width, Bool())
    val pageFaults = Vec(width, Bool())
    val faultOffsets = Vec(width, UInt(5.W))
    val denied = Vec(2 * width, Bool())
}

class FetchPhaseStatus(width: Int) extends Bundle {
    val tokenValid = Bool()
    val tokenPc = UInt(64.W)
    val tokenPresent = UInt(width.W)
    val accepted = UInt(width.W)
    val transferred = Bool()
}

/** Compact, registered instruction reservoir between the fetch cache and decode.
  *
  * Capacity is two rename packets; minimum latency is one cycle, and both ports
  * sustain renameWidth instructions per cycle. Input credits use registered
  * occupancy only: neither decode acceptance nor a prediction can feed through
  * to raw fetch admission. Default dedicated head slots avoid a pointer-indexed
  * read; optional circularPayload leaves payload static and adds bank-read muxes.
  * A partial dequeue retains the surviving instructions, allowing two-wide
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
    parallelValidation: Boolean = false, hintEntries: Int = 8, splitCursor: Boolean = false,
    bankedHints: Boolean = false, val alignedPermissionStage: Boolean = false,
    val eagerPrefixSelect: Boolean = false, val acceptedPrefixValidation: Boolean = false,
    val circularPayload: Boolean = false) extends Module {
    require(width >= 1 && width <= 4)
    require(!alignedPermissionStage || (width == 2 && compressed && splitCursor),
        "aligned permission phase requires two compressed lanes and split cursor")
    require(!eagerPrefixSelect || alignedPermissionStage,
        "direct eager prefix selection requires the aligned permission phase")
    require(!acceptedPrefixValidation || (parallelValidation && width == 2),
        "accepted-prefix validation requires the qualified two-lane parallel-validation caller")
    require(!circularPayload || (width == 2 && !alignedPermissionStage),
        "circular fetch payload currently supports two lanes without the optional permission phase")
    require(resetPc >= 0 && resetPc < (BigInt(1) << 64))
    require(Set(8, 16, 32).contains(hintEntries))
    private val capacity = 2 * width
    private val countBits = log2Ceil(capacity + 1)
    private val offsetBits = log2Ceil(4 * width + 1)
    val io = IO(new Bundle {
        val supply = Input(Vec(width, Valid(new RawFetchInstruction)))
        val phaseInput = if (alignedPermissionStage) Some(Input(new FetchPhaseInput(width))) else None
        val phaseStatus = if (alignedPermissionStage) Some(Output(new FetchPhaseStatus(width))) else None
        val requestFrontier = if (alignedPermissionStage) Some(Output(UInt(64.W))) else None
        val suppressRequest = if (alignedPermissionStage) Some(Output(Bool())) else None
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
    val circular = if (circularPayload) Some(Module(new CircularFetchInstructionStorage)) else None
    val slots = if (circularPayload) None else Some(Reg(Vec(capacity, new RawFetchInstruction)))
    val count = circular.map(_.io.occupancy).getOrElse(RegInit(0.U(countBits.W)))
    def queuedPc(slot: Int): UInt = circular.map(_.io.lookaheadPc(slot)).getOrElse(slots.get(slot).pc)
    val rawCursor = RegInit(resetPc.U(64.W))
    // A correction is captured without a late conditional write-enable. The
    // registered selector overrides speculative raw progress on the next cycle,
    // with exactly the old redirect latency. Decode/path validation cannot
    // drive the normal cursor's data or CE. No offered instruction survives a
    // same-cycle correction; the cancelled raw cursor is simply unobservable.
    val correctionPc = if (splitCursor) Some(Reg(UInt(64.W))) else None
    val correctionPending = if (splitCursor) Some(RegInit(false.B)) else None
    val supplyPc = if (splitCursor) Mux(correctionPending.get, correctionPc.get, rawCursor) else rawCursor
    // The token contains 146 payload bits at width two, plus two presence bits.
    // PMP candidate facts and aligned transport metadata cross the same edge.
    val token = if (alignedPermissionStage) Some(Reg(new FetchPhaseToken(width))) else None
    val tokenPresent = if (alignedPermissionStage) Some(RegInit(0.U(width.W))) else None
    val tokenValid = tokenPresent.map(_(0)).getOrElse(false.B)
    val tokenCount = tokenPresent.map(PopCount(_)).getOrElse(0.U)
    val tokenTransfer = alignedPermissionStage.B && tokenValid && !io.pause &&
        count +& tokenCount <= capacity.U
    val tokenReady = !tokenValid || tokenTransfer
    val resolutionPc = token.map(_.pc).getOrElse(supplyPc)
    val resolutionSupply = Wire(Vec(width, Valid(new RawFetchInstruction)))
    resolutionSupply := io.supply
    if (alignedPermissionStage) {
        for (lane <- 0 until width) {
            resolutionSupply(lane).valid := tokenPresent.get(lane) && tokenTransfer
            resolutionSupply(lane).bits.pc := 0.U
            resolutionSupply(lane).bits.nextPc := 0.U
            resolutionSupply(lane).bits.instruction := token.get.instructions(lane)
            resolutionSupply(lane).bits.accessFault := token.get.accessFaults(lane)
            resolutionSupply(lane).bits.pageFault := token.get.pageFaults(lane)
            resolutionSupply(lane).bits.faultAddress :=
                Cat(token.get.pc(63, 3), 0.U(3.W)) + token.get.faultOffsets(lane)
        }
        io.requestFrontier.get := Mux(tokenValid, token.get.pc, supplyPc)
        io.phaseStatus.get.tokenValid := tokenValid
        io.phaseStatus.get.tokenPc := token.get.pc
        io.phaseStatus.get.tokenPresent := tokenPresent.get
    }
    private val hintBits = log2Ceil(hintEntries)
    def hintIndex(address: UInt): UInt = address(hintBits, 1) ^ address(2 * hintBits, hintBits + 1)
    val hintAddresses = Wire(Vec(width, UInt(hintBits.W)))
    val hintReads = Wire(Vec(width, Valid(new FetchHintPayload)))
    if (bankedHints) {
        val hints = Module(new OwnerBankedFetchHints(hintEntries, width))
        hints.io.address := hintAddresses
        hints.io.invalidate := io.invalidate
        hintReads := hints.io.read
        for (lane <- 0 until width) {
            val train = io.train(lane)
            val short = compressed.B && train.bits.instruction(1, 0) =/= 3.U
            val sequential = train.bits.pc + Mux(short, 2.U, 4.U)
            hints.io.write(lane).valid := train.valid
            hints.io.write(lane).bits.index := hintIndex(train.bits.pc)
            hints.io.write(lane).bits.data.pc := train.bits.pc
            hints.io.write(lane).bits.data.instruction := train.bits.instruction
            hints.io.write(lane).bits.data.nextPc := train.bits.nextPc
            hints.io.write(lane).bits.data.aligned := (if (compressed) !train.bits.nextPc(0)
                else train.bits.nextPc(1, 0) === 0.U)
            hints.io.write(lane).bits.data.different := train.bits.nextPc =/= sequential
        }
    } else {
        val hintValid = RegInit(VecInit(Seq.fill(hintEntries)(false.B)))
        val hintPc = Reg(Vec(hintEntries, UInt(64.W)))
        val hintInstruction = Reg(Vec(hintEntries, UInt(32.W)))
        val hintNextPc = Reg(Vec(hintEntries, UInt(64.W)))
        val hintAligned = Reg(Vec(hintEntries, Bool()))
        val hintDifferent = Reg(Vec(hintEntries, Bool()))
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
        for (lane <- 0 until width) {
            val index = hintAddresses(lane)
            hintReads(lane).valid := BankedOneHotRead(hintValid, index)
            hintReads(lane).bits.pc := BankedOneHotRead(hintPc, index)
            hintReads(lane).bits.instruction := BankedOneHotRead(hintInstruction, index)
            hintReads(lane).bits.nextPc := BankedOneHotRead(hintNextPc, index)
            hintReads(lane).bits.aligned := BankedOneHotRead(hintAligned, index)
            hintReads(lane).bits.different := BankedOneHotRead(hintDifferent, index)
        }
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
    val cursorBases = if (alignedPermissionStage) Seq(token.get.pc)
        else if (splitCursor) Seq(rawCursor, correctionPc.get) else Seq(rawCursor)
    val cursorHighs = cursorBases.map(_(63, 21))
    // High-word +/-1 is prepared in parallel eight-bit slices before any hint,
    // jump or correction selection. Preserve packet/redirect latency and the
    // exact 2MiB/XLEN wrap behavior without a six-CARRY8 high-word chain.
    val incrementedHighs = cursorHighs.map(high => TimingArithmetic.neighbor(high))
    val decrementedHighs = cursorHighs.map(high => TimingArithmetic.neighbor(high, decrement = true))
    def selectCursor(values: Seq[UInt]): UInt =
        if (splitCursor && !alignedPermissionStage) Mux(correctionPending.get, values(1), values(0)) else values.head
    val pcCandidates = (0 to 2 * width).map { offset =>
        val alternatives = cursorBases.indices.map { base =>
            val low = cursorBases(base)(20, 0) +& (2 * offset).U
            Cat(Mux(low(21), incrementedHighs(base), cursorHighs(base)), low(20, 0))
        }
        (2 * offset).U -> selectCursor(alternatives)
    }
    def rawPc(offset: UInt): UInt = MuxLookup(offset, resolutionPc)(pcCandidates)
    capturePrefix(0) := !io.pause
    byteOffsets(0) := 0.U
    for (lane <- 0 until width) {
        io.instructions(lane).valid := count > lane.U
        io.instructions(lane).bits := circular.map(_.io.instructions(lane).bits).getOrElse(slots.get(lane))
        capturePrefix(lane + 1) := capturePrefix(lane) && resolutionSupply(lane).valid &&
            count <= (capacity - lane - 1).U &&
            (if (lane == 0) true.B else !rawTaken(lane - 1))
        val instruction = resolutionSupply(lane).bits.instruction
        val short = compressed.B && instruction(1, 0) =/= 3.U
        byteOffsets(lane + 1) := byteOffsets(lane) + Mux(short, 2.U, 4.U)
        rawPcs(lane) := rawPc(byteOffsets(lane))
        if (alignedPermissionStage) {
            // Select the captured candidates only after the boundary. This
            // prevents PMP and live alignment from entering rawTaken/scan CE.
            def deniedAt(offset: UInt): Bool = MuxLookup(offset, token.get.denied(0))(
                token.get.denied.zipWithIndex.map { case (value, n) => (2 * n).U -> value })
            val firstDenied = deniedAt(byteOffsets(lane))
            val secondDenied = !short && deniedAt(byteOffsets(lane) + 2.U)
            val denied = firstDenied || secondDenied
            resolutionSupply(lane).bits.accessFault := token.get.accessFaults(lane) || denied
            when(denied && !token.get.accessFaults(lane) && !token.get.pageFaults(lane)) {
                resolutionSupply(lane).bits.faultAddress :=
                    Mux(firstDenied, rawPcs(lane), rawPc(byteOffsets(lane) + 2.U))
            }
        }
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
        hintAddresses(lane) := index
        val selectedValid = hintReads(lane).valid
        val selectedPc = hintReads(lane).bits.pc
        val selectedInstruction = hintReads(lane).bits.instruction
        val selectedNextPc = hintReads(lane).bits.nextPc
        val selectedAligned = hintReads(lane).bits.aligned
        val selectedDifferent = hintReads(lane).bits.different
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
        val fault = resolutionSupply(lane).bits.accessFault || resolutionSupply(lane).bits.pageFault
        val priorFault = (0 until lane).map(earlier =>
            resolutionSupply(earlier).bits.accessFault || resolutionSupply(earlier).bits.pageFault)
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
    if (acceptedPrefixValidation) {
        // IntegerCore drives both inputs from the very same accepted rename lanes.
        // This is checked at the real module boundary, not assumed from a profile.
        assert(io.expectedNext.valid === io.consume.asUInt.orR,
            "specialized fetch validation must name exactly an accepted nonempty prefix")
    }
    // Raw offers can be observed while a redirect wins. Flush has last state
    // priority, so they cannot occupy a slot or advance the next supply PC.
    val captured = PopCount(capturePrefix.drop(1))
    val remaining = count - consumed
    if (circularPayload) {
        circular.get.io.consume := io.consume
        for (lane <- 0 until width) {
            circular.get.io.capture(lane).valid := capturePrefix(lane + 1)
            circular.get.io.capture(lane).bits := resolutionSupply(lane).bits
            circular.get.io.capture(lane).bits.pc := rawPcs(lane)
            circular.get.io.capture(lane).bits.nextPc := rawNextPcs(lane)
        }
    } else {
        for (slot <- 0 until capacity) {
            when(consumed =/= 0.U && slot.U < remaining) {
                slots.get(slot) := MuxLookup(consumed, slots.get(slot))(
                    (1 to width).filter(slot + _ < capacity).map { shift =>
                        shift.U -> slots.get(slot + shift)
                    })
            }
            for (lane <- 0 until width) {
                when(capturePrefix(lane + 1) && remaining + lane.U === slot.U) {
                    slots.get(slot) := resolutionSupply(lane).bits
                    slots.get(slot).pc := rawPcs(lane)
                    slots.get(slot).nextPc := rawNextPcs(lane)
                }
            }
        }
        count := remaining + captured
    }
    // Captures form a contiguous prefix. Select its last lane directly, keeping
    // the occupancy PopCount out of the successor control path. No capture
    // holds the supply PC; a captured lane retains its fault-qualified next PC.
    val lastCaptured = (0 until width).map { lane =>
        capturePrefix(lane + 1) && (if (lane + 1 == width) true.B else !capturePrefix(lane + 2))
    }
    val supplySuccessor = Mux1H(Seq(!capturePrefix(1) -> resolutionPc) ++
        lastCaptured.zip(rawNextPcs))
    // Compare the first surviving instruction, not the cursor several words
    // ahead. If no instruction survives, a matching offer or cursor is enough.
    // This keeps an already-correct taken path and discards a stale early hint.
    val queuedSuccessor = MuxLookup(consumed, queuedPc(0))(
        (1 to width).filter(_ < capacity).map(lanes => lanes.U -> queuedPc(lanes)))
    // An unresolved token is older than the eager scanner even when it is
    // blocked from transfer. Both validation forms must inspect that token.
    val unqueuedSuccessor = Mux(tokenValid, resolutionPc, supplyPc)
    val firstSuccessor = Mux(remaining =/= 0.U, queuedSuccessor, unqueuedSuccessor)
    val mismatch = if (parallelValidation) {
        // Compare registered queue candidates against both early alternatives
        // before PMP/rename selects a prefix. Late admission selects one BIT,
        // rather than a 64-bit successor mux followed by a 64-bit comparator.
        val candidates = (1 to width).map { lanes =>
            val observed = Mux(count > lanes.U, queuedPc(lanes), unqueuedSuccessor)
            val validation = io.validation.get(lanes - 1)
            consumed === lanes.U && Mux(validation.predicts,
                observed =/= validation.predictedPc, observed =/= validation.sequentialPc)
        }
        val acceptedMismatch = candidates.reduce(_ || _)
        if (acceptedPrefixValidation) acceptedMismatch
        else acceptedMismatch || (consumed === 0.U && firstSuccessor =/= io.expectedNext.bits)
    } else firstSuccessor =/= io.expectedNext.bits
    val wrongPath = io.expectedNext.valid && mismatch
    // invalidate retains its historical hint-only meaning here. Real core
    // context changes also assert flush with the exact architectural restart PC.
    val cancel = io.flush.valid || wrongPath
    circular.foreach(_.io.cancel := cancel)
    for (lane <- 0 until width) {
        io.captured(lane) := capturePrefix(lane + 1) && !cancel
    }
    val rawCorrection = alignedPermissionStage.B &&
        (0 until width).map(lane => capturePrefix(lane + 1) && rawTaken(lane)).reduce(_ || _)
    if (alignedPermissionStage) {
        // Eager sequential scanning has its own recurrence. It uses completed
        // PC+{0,2,4,6,8} alternatives and registered-only token/reservoir credit.
        // A later B correction cancels the speculative A write without entering
        // this cursor's arithmetic or write-enable.
        val scanPrefix = Wire(Vec(width + 1, Bool()))
        scanPrefix(0) := !io.pause && tokenReady
        for (lane <- 0 until width) {
            scanPrefix(lane + 1) := scanPrefix(lane) && io.supply(lane).valid
        }
        val scanBases = Seq(rawCursor, correctionPc.get)
        val scanHighs = scanBases.map(_(63, 21))
        val scanIncremented = scanHighs.map(high => TimingArithmetic.neighbor(high))
        val scanCandidates = (0 to 2 * width).map { halfwords =>
            val alternatives = scanBases.indices.map { base =>
                val low = scanBases(base)(20, 0) +& (2 * halfwords).U
                Cat(Mux(low(21), scanIncremented(base), scanHighs(base)), low(20, 0))
            }
            (2 * halfwords).U -> Mux(correctionPending.get, alternatives(1), alternatives(0))
        }
        val scanNext = if (eagerPrefixSelect) {
            // scanPrefix(2) implies scanPrefix(1). The accepted prefix advances
            // by zero, one 2/4-byte instruction, or two such instructions.
            // Keep the completed full-width carry/correction candidates intact.
            val one = scanPrefix(1) && !scanPrefix(2)
            val long0 = io.supply(0).bits.instruction(1, 0) === 3.U
            val long1 = io.supply(1).bits.instruction(1, 0) === 3.U
            val selected = Seq(
                !scanPrefix(1),
                one && !long0,
                (one && long0) || (scanPrefix(2) && !long0 && !long1),
                scanPrefix(2) && (long0 ^ long1),
                scanPrefix(2) && long0 && long1)
            Mux1H(selected.zip(scanCandidates.map(_._2)))
        } else {
            val scanOffsets = Wire(Vec(width + 1, UInt(offsetBits.W)))
            scanOffsets(0) := 0.U
            for (lane <- 0 until width) {
                val short = compressed.B && io.supply(lane).bits.instruction(1, 0) =/= 3.U
                scanOffsets(lane + 1) := scanOffsets(lane) + Mux(short, 2.U, 4.U)
            }
            Mux1H(Seq(!scanPrefix(1) -> supplyPc) ++ (0 until width).map { lane =>
                val last = scanPrefix(lane + 1) && (if (lane + 1 == width) true.B else !scanPrefix(lane + 2))
                last -> MuxLookup(scanOffsets(lane + 1), supplyPc)(scanCandidates)
            })
        }
        rawCursor := scanNext
        when(tokenTransfer) { tokenPresent.get := 0.U }
        when(scanPrefix(1)) { tokenPresent.get := VecInit(scanPrefix.drop(1)).asUInt }
        // Credit, not alignment/presence, controls replacement of dead token
        // payload. A stalled valid token has tokenReady=false and still holds
        // every field. Presence and correction priority remain unchanged.
        when(scanPrefix(0)) {
            token.get.pc := supplyPc
            for (lane <- 0 until width) {
                token.get.instructions(lane) := io.supply(lane).bits.instruction
                token.get.accessFaults(lane) := io.supply(lane).bits.accessFault
                token.get.pageFaults(lane) := io.supply(lane).bits.pageFault
                token.get.faultOffsets(lane) := io.phaseInput.get.faultOffsets(lane)
            }
            token.get.denied := io.phaseInput.get.denied
        }
        when(cancel || rawCorrection) { tokenPresent.get := 0.U }
        val corrected = Mux(io.flush.valid, io.flush.bits,
            Mux(wrongPath, io.expectedNext.bits, supplySuccessor))
        correctionPc.get := corrected
        correctionPending.get := cancel || rawCorrection
        io.nextFetchPc := Mux(cancel || rawCorrection, corrected, scanNext)
        io.suppressRequest.get := cancel || rawCorrection
        io.phaseStatus.get.accepted := Mux(cancel || rawCorrection, 0.U,
            VecInit(scanPrefix.drop(1)).asUInt)
        io.phaseStatus.get.transferred := tokenTransfer && !cancel
    } else {
        io.nextFetchPc := Mux(io.flush.valid, io.flush.bits,
            Mux(wrongPath, io.expectedNext.bits, supplySuccessor))
        if (splitCursor) {
            rawCursor := supplySuccessor
            correctionPc.get := Mux(io.flush.valid, io.flush.bits, io.expectedNext.bits)
            correctionPending.get := cancel
        } else rawCursor := io.nextFetchPc
    }
    if (!circularPayload) when(cancel) {
        count := 0.U
    }
    if (acceptedPrefixValidation) {
        when(cancel) {
            assert(!io.captured.asUInt.orR, "correction must cancel all same-edge captures")
            assert(io.nextFetchPc === Mux(io.flush.valid, io.flush.bits, io.expectedNext.bits),
                "flush must retain priority over accepted-prefix correction")
        }
        when(!io.consume.asUInt.orR) {
            assert(!wrongPath, "zero accepted lanes cannot trigger specialized path validation")
        }
    }
    io.fetchPc := supplyPc
    io.occupancy := count
    assert(count <= capacity.U, "fetch reservoir capacity exceeded")
}
