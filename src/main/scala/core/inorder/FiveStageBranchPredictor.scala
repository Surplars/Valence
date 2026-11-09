package soc.core.inorder

import chisel3._
import chisel3.util._

class FiveStageBranchTraining(val p: FiveStageConfig) extends Bundle {
    val pc = UInt(p.xlen.W)
    val controlFlow = Bool()
    val conditional = Bool()
    val taken = Bool()
    val target = UInt(p.xlen.W)
    val compressed = Bool()
}

/** Scalar leaves also keep the pinned GSIM top-level C++ getters well typed. */
class FiveStagePredictionValues(xlen: Int, banks: Int) extends Bundle {
    val plusTwo = UInt(xlen.W)
    val plusFour = UInt(xlen.W)
    val target0 = UInt(xlen.W)
    val target1 = if (banks >= 2) Some(UInt(xlen.W)) else None
    val target2 = if (banks >= 3) Some(UInt(xlen.W)) else None
    val target3 = if (banks >= 4) Some(UInt(xlen.W)) else None
    def all: Seq[UInt] = Seq(plusTwo, plusFour, target0) ++ Seq(target1, target2, target3).flatten
}

/** Tagged BTB + saturating bimodal direction counter, explicitly small distributed RAM.
  * No speculative training, payload reset, RAS or hidden architectural pipeline stage.
  * Lookup is combinational; the fetch owner captures its prediction at request acceptance.
  * A false BTB hit on modified code is repaired in EX; FENCE.I clears all valid metadata.
  */
class FiveStageBranchPredictor(val p: FiveStageConfig) extends Module {
    require(p.branchPredictorEntries > 0)
    val bankCount = if (p.fpgaTimingCuts) math.min(4, p.branchPredictorEntries / 2) else 1
    val io = IO(new Bundle {
        val pc = Input(UInt(p.xlen.W))
        val nextPc = Output(UInt(p.xlen.W))
        val hit = Output(Bool())
        val taken = Output(Bool())
        val compressed = Output(Bool())
        val train = Flipped(Valid(new FiveStageBranchTraining(p)))
        val invalidate = Input(Bool())
        val candidateMask = if (p.fpgaTimingCuts) Some(Output(UInt((bankCount + 2).W))) else None
        val candidateValues = if (p.fpgaTimingCuts)
            Some(Output(new FiveStagePredictionValues(p.xlen, bankCount))) else None
    })
    val indexBits = log2Ceil(p.branchPredictorEntries)
    val alignmentBits = if (p.withC) 1 else 2
    val tagBits = p.xlen - indexBits - alignmentBits
    class Entry extends Bundle {
        val tag = UInt(tagBits.W)
        val target = UInt(p.xlen.W)
        // Fold control-flow class and counter direction on training, before
        // the lookup edge. Retain the full counter for identical saturation.
        val predictsTaken = Bool()
        val counter = UInt(2.W)
        val compressed = Bool()
    }
    // Same logical entries and RAM bits. Low index bits select shallow
    // banks after parallel reads; upper bits address each local RAM. Keeping
    // the hottest low PC bits off every RAM address shortens PC feedback.
    val bankRows = p.branchPredictorEntries / bankCount
    val rowBits = log2Ceil(bankRows)
    val entries = Seq.fill(bankCount)(Mem(bankRows, new Entry))
    chisel3.experimental.annotate(this)(Seq(firrtl.AttributeAnnotation(this.toNamed,
        "ram_style = \"distributed\"")))
    // Logical invalidation is immediate; raw bit clearing stays behind one
    // local guard per bank, without a global reset/CE on every validity bit.
    val validBanks = Seq.fill(bankCount)(Module(new I1BranchBankValid(bankRows)))
    // Length is a one-bit hint for EVERY instruction, not a BTB allocation.
    // Aliases may choose the wrong length and are repaired by the normal PC
    // check; they must never evict a useful control-flow target/counter.
    val lengthBanks = if (p.fpgaTimingCuts && p.withC)
        Seq.fill(bankCount)(Module(new I1BranchBankValid(bankRows))) else Seq.empty

    // With C, old halfword indexing wasted half the RAM for aligned32 code.
    // Fold bit1 into the top index bit; the tag below retains the other
    // independent index bit so halfwords and aliases remain distinguishable.
    def index(pc: UInt): UInt = {
        val base = if (p.withC && p.fpgaTimingCuts)
            pc(indexBits + 1, 2) ^ Mux(pc(1), (BigInt(1) << (indexBits - 1)).U(indexBits.W), 0.U(indexBits.W))
            else pc(indexBits + alignmentBits - 1, alignmentBits)
        // The upper slice is already present in the exact tag. XORing it into
        // the index is invertible for a given tag, so no tag bit is discarded.
        // This changes conflicts, not capacity, RAM width, latency or ownership.
        val shift = if (p.withC && p.fpgaTimingCuts) 2 else alignmentBits
        if (p.hashedBranchIndex) base ^ pc(shift + 2 * indexBits - 1, shift + indexBits) else base
    }
    def tag(pc: UInt): UInt = if (p.withC && p.fpgaTimingCuts)
        // The folded index already fixes pc(high)^pc(1). Given an equal
        // upper tag, comparing the high bit is equivalent to comparing bit1,
        // and keeps the hottest halfword bit out of the RAM tag comparator.
        Cat(pc(p.xlen - 1, indexBits + 2), pc(indexBits + 1)) else pc(p.xlen - 1, indexBits + alignmentBits)
    val bankBits = log2Ceil(bankCount)
    // Keep the folded halfword bit in the late bank select rather than the
    // RAM row address. This is a physical permutation of the SAME logical
    // index: aliases, direction counters and independent length hints are unchanged.
    private val halfwordBanks = p.withC && p.fpgaTimingCuts && bankCount > 1
    def row(i: UInt): UInt = if (bankCount == 1) i(rowBits - 1, 0)
        else if (halfwordBanks) i(indexBits - 2, bankBits - 1) else i(indexBits - 1, bankBits)
    def bank(i: UInt): UInt = if (bankCount == 1) 0.U
        else if (halfwordBanks && bankCount == 4) Cat(i(indexBits - 1), i(0))
        else if (halfwordBanks) i(indexBits - 1) else i(bankBits - 1, 0)
    val lookupIndex = index(io.pc)
    val lookups = entries.map(_.read(row(lookupIndex)))
    validBanks.foreach { valid =>
        valid.io.lookupRow := row(lookupIndex)
        valid.io.trainingRow := row(index(io.train.bits.pc))
        valid.io.invalidate := io.invalidate
    }
    val hits = lookups.zipWithIndex.map { case (entry, b) =>
        bank(lookupIndex) === b.U && validBanks(b).io.lookupValid &&
            (if (p.fpgaTimingCuts) I1TimingMath.equal(entry.tag, tag(io.pc)) else entry.tag === tag(io.pc))
    }
    io.hit := hits.reduce(_ || _)
    // Prepare both fixed increments before RAM hit/length arrives. No late
    // variable addend/carry-in through a full XLEN PC feedback chain.
    val plusTwo = if (p.fpgaTimingCuts) I1TimingMath.incrementPowerOfTwo(io.pc, 1, 8) else io.pc + 2.U
    val plusFour = if (p.fpgaTimingCuts) I1TimingMath.incrementPowerOfTwo(io.pc, 2, 8) else io.pc + 4.U
    val takeTargets = lookups.zipWithIndex.map { case (entry, b) =>
        if (p.fpgaTimingCuts) bank(lookupIndex) === b.U && validBanks(b).io.lookupValid &&
            I1TimingMath.equal(Cat(entry.tag, entry.predictsTaken), Cat(tag(io.pc), true.B))
        else hits(b) && entry.predictsTaken
    }
    val takeTarget = takeTargets.reduce(_ || _)
    io.taken := takeTarget
    lengthBanks.zipWithIndex.foreach { case (length, b) =>
        length.io.lookupRow := row(lookupIndex)
        length.io.trainingRow := row(index(io.train.bits.pc))
        length.io.invalidate := io.invalidate
        val selected = io.train.valid && bank(index(io.train.bits.pc)) === b.U
        length.io.allocate := selected && io.train.bits.compressed
        length.io.remove := selected && !io.train.bits.compressed
    }
    val shortSequential = if (lengthBanks.nonEmpty) lengthBanks.zipWithIndex.map { case (length, b) =>
        bank(lookupIndex) === b.U && length.io.lookupValid
    }.reduce(_ || _) else p.withC.B && lookups.zip(hits).map { case (entry, hit) =>
        hit && entry.compressed
    }.reduce(_ || _)
    io.compressed := shortSequential
    // Resolve bank-local permission/direction in parallel; do not first
    // select the whole Entry, then compare its tag, then choose the target.
    val legacyNextPc = Mux1H(Seq((!takeTarget && shortSequential) -> plusTwo,
        (!takeTarget && !shortSequential) -> plusFour) ++
        takeTargets.zip(lookups.map(_.target)))
    if (p.fpgaTimingCuts) {
        // Expose the exclusive alternatives for checks and the core's final
        // PC selection. Local permission is combined with recovery selection
        // before the wide correction, avoiding two serial wide PC muxes.
        val masks = Seq(!takeTarget && shortSequential, !takeTarget && !shortSequential) ++ takeTargets
        val values = Seq(plusTwo, plusFour) ++ lookups.map(_.target)
        io.candidateMask.get := VecInit(masks).asUInt
        io.candidateValues.get.all.zip(values).foreach { case (out, value) => out := value }
        // The default PC is unconditional. Each bank supplies only its XOR
        // correction, qualified by its OWN hit. No all-banks taken reduction
        // then inverted default mask lies after the late tag comparison.
        val sequential = Mux(shortSequential, plusTwo, plusFour)
        val corrections = lookups.zip(takeTargets).map { case (entry, take) =>
            (entry.target ^ sequential) & Fill(p.xlen, take)
        }
        io.nextPc := sequential ^ corrections.reduce(_ | _)
        when(!reset.asBool) {
            assert(PopCount(VecInit(masks)) === 1.U, "prediction alternatives must be exclusive")
            assert(io.nextPc === legacyNextPc, "bank-local prediction changed exact next PC")
        }
    } else io.nextPc := legacyNextPc
    val trainingIndex = index(io.train.bits.pc)
    for ((memory, b) <- entries.zipWithIndex) {
        // Read, compare and update the direction counter locally. Selecting a
        // wide shared training Entry before comparing its tag puts the bank
        // mux on every write-feedback path and fans it back across all banks.
        val trainingEntry = memory.read(row(trainingIndex))
        val tagMatch = if (p.fpgaTimingCuts) I1TimingMath.equal(trainingEntry.tag, tag(io.train.bits.pc))
            else trainingEntry.tag === tag(io.train.bits.pc)
        val oldHit = validBanks(b).io.trainingValid && tagMatch
        val updated = Wire(new Entry)
        updated.tag := tag(io.train.bits.pc)
        updated.target := io.train.bits.target
        updated.compressed := p.withC.B && io.train.bits.compressed
        // Each result bit is a bounded Boolean function, rather than a
        // replicated increment/decrement/equality/priority-mux chain.
        val high = trainingEntry.counter(1)
        val low = trainingEntry.counter(0)
        val taken = io.train.bits.taken
        val saturated = Cat(Mux(taken, high || low, high && low),
            Mux(taken, high || !low, high && !low))
        updated.counter := Mux(oldHit, saturated, Cat(taken, !taken))
        updated.predictsTaken := io.train.bits.controlFlow &&
            (!io.train.bits.conditional || updated.counter(1))
        val selected = io.train.valid && bank(trainingIndex) === b.U
        val allocate = selected && (io.train.bits.controlFlow || (p.withC && !p.fpgaTimingCuts).B)
        // An already-invalid row can also be cleared. Removing its valid
        // read from this late tag-match feedback does not change any owner.
        validBanks(b).io.allocate := allocate
        validBanks(b).io.remove := selected && !io.train.bits.controlFlow && (!p.withC || p.fpgaTimingCuts).B && tagMatch
        when(allocate) { memory.write(row(trainingIndex), updated) }
    }
}
