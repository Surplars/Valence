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
    def all: Seq[UInt] = Seq(plusTwo, plusFour, target0) ++ target1.toSeq
}

/** Tagged BTB + saturating bimodal direction counter, explicitly small distributed RAM.
  * No speculative training, payload reset, RAS or hidden architectural pipeline stage.
  * Lookup is combinational; the fetch owner captures its prediction at request acceptance.
  * A false BTB hit on modified code is repaired in EX; FENCE.I clears all valid metadata.
  */
object FiveStageBranchPredictor {
    // Two banks shorten the PC selection while retaining every indexed entry.
    def bankCount(p: FiveStageConfig): Int =
        if (p.fpgaTimingCuts) math.min(2, p.branchPredictorEntries / 2) else 1
}

class FiveStageBranchPredictor(val p: FiveStageConfig) extends Module {
    require(p.branchPredictorEntries > 0)
    val bankCount = FiveStageBranchPredictor.bankCount(p)
    val io = IO(new Bundle {
        val pc = Input(UInt(p.xlen.W))
        val nextPc = Output(UInt(p.xlen.W))
        val hit = Output(Bool())
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
        val conditional = Bool()
        val counter = UInt(2.W)
        val controlFlow = Bool()
        val compressed = Bool()
    }
    // Same entries and RAM bits. Select two parallel 64-row banks after
    // their local comparisons instead of four targets on the PC feedback path.
    val bankRows = p.branchPredictorEntries / bankCount
    val rowBits = log2Ceil(bankRows)
    val entries = Seq.fill(bankCount)(Mem(bankRows, new Entry))
    chisel3.experimental.annotate(this)(Seq(firrtl.AttributeAnnotation(this.toNamed,
        "ram_style = \"distributed\"")))
    // Logical invalidation is immediate; raw bit clearing stays behind one
    // local guard per bank, without a global reset/CE on every validity bit.
    val validBanks = Seq.fill(bankCount)(Module(new I1BranchBankValid(bankRows)))
    // With C, old halfword indexing wasted half the RAM for aligned32 code.
    // Fold bit1 into the top index bit; KEEP bit1 in the tag so the mapping
    // remains injective across halfwords and aliases. Same RAM/tag width.
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
        Cat(pc(p.xlen - 1, indexBits + 2), pc(1)) else pc(p.xlen - 1, indexBits + alignmentBits)
    def row(i: UInt): UInt = i(rowBits - 1, 0)
    def bank(i: UInt): UInt = if (bankCount == 1) 0.U else i(indexBits - 1, rowBits)
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
    val takeTargets = lookups.zip(hits).map { case (entry, hit) =>
        hit && entry.controlFlow && (!entry.conditional || entry.counter(1))
    }
    val takeTarget = takeTargets.reduce(_ || _)
    val shortSequential = p.withC.B && lookups.zip(hits).map { case (entry, hit) =>
        hit && entry.compressed
    }.reduce(_ || _)
    // Resolve bank-local permission/direction in parallel; do not first
    // select the whole Entry, then compare its tag, then choose the target.
    val legacyNextPc = Mux1H(Seq((!takeTarget && shortSequential) -> plusTwo,
        (!takeTarget && !shortSequential) -> plusFour) ++
        takeTargets.zip(lookups.map(_.target)))
    if (p.fpgaTimingCuts) {
        // Keep the mutually exclusive alternatives separate through the
        // core's redirect/kill selection. A predictor result must not cross
        // another XLEN priority mux after its tag/length/target reduction.
        val masks = Seq(!takeTarget && shortSequential, !takeTarget && !shortSequential) ++ takeTargets
        val values = Seq(plusTwo, plusFour) ++ lookups.map(_.target)
        io.candidateMask.get := VecInit(masks).asUInt
        io.candidateValues.get.all.zip(values).foreach { case (out, value) => out := value }
        // The default PC is unconditional. Each bank supplies only its XOR
        // correction, qualified by its OWN hit. No all-banks taken reduction
        // then inverted default mask lies after the late tag comparison.
        val corrections = lookups.zip(hits).map { case (entry, hit) =>
            val target = entry.controlFlow && (!entry.conditional || entry.counter(1))
            val short = p.withC.B && entry.compressed
            val changed = Mux(target, entry.target, plusTwo) ^ plusFour
            changed & Fill(p.xlen, hit && (target || short))
        }
        io.nextPc := plusFour ^ corrections.reduce(_ | _)
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
        updated.conditional := io.train.bits.conditional
        updated.controlFlow := io.train.bits.controlFlow
        updated.compressed := p.withC.B && io.train.bits.compressed
        // Each result bit is a bounded Boolean function, rather than a
        // replicated increment/decrement/equality/priority-mux chain.
        val high = trainingEntry.counter(1)
        val low = trainingEntry.counter(0)
        val taken = io.train.bits.taken
        val saturated = Cat(Mux(taken, high || low, high && low),
            Mux(taken, high || !low, high && !low))
        updated.counter := Mux(oldHit, saturated, Cat(taken, !taken))
        val selected = io.train.valid && bank(trainingIndex) === b.U
        val allocate = selected && (io.train.bits.controlFlow || p.withC.B)
        // An already-invalid row can also be cleared. Removing its valid
        // read from this late tag-match feedback does not change any owner.
        validBanks(b).io.allocate := allocate
        validBanks(b).io.remove := selected && !io.train.bits.controlFlow && !p.withC.B && tagMatch
        when(allocate) { memory.write(row(trainingIndex), updated) }
    }
}
