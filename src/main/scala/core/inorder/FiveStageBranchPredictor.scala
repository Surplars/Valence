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

/** Tagged BTB + saturating bimodal direction counter, explicitly small distributed RAM.
  * No speculative training, payload reset, RAS or hidden architectural pipeline stage.
  * Lookup is combinational; the fetch owner captures its prediction at request acceptance.
  * A false BTB hit on modified code is repaired in EX; FENCE.I clears all valid metadata.
  */
class FiveStageBranchPredictor(val p: FiveStageConfig) extends Module {
    require(p.branchPredictorEntries > 0)
    val io = IO(new Bundle {
        val pc = Input(UInt(p.xlen.W))
        val nextPc = Output(UInt(p.xlen.W))
        val hit = Output(Bool())
        val train = Flipped(Valid(new FiveStageBranchTraining(p)))
        val invalidate = Input(Bool())
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
    // Same entries and RAM bits. In FPGA mode the upper index selects four
    // shallow banks AFTER their parallel reads, rather than steering a deep
    // 128-row RAM mux before tag/length/direction and the PC feedback mux.
    val bankCount = if (p.fpgaTimingCuts) math.min(4, p.branchPredictorEntries / 2) else 1
    val bankRows = p.branchPredictorEntries / bankCount
    val rowBits = log2Ceil(bankRows)
    val entries = Seq.fill(bankCount)(Mem(bankRows, new Entry))
    chisel3.experimental.annotate(this)(Seq(firrtl.AttributeAnnotation(this.toNamed,
        "ram_style = \"distributed\"")))
    val valid = RegInit(0.U(p.branchPredictorEntries.W))
    // With C, old halfword indexing wasted half the RAM for aligned32 code.
    // Fold bit1 into the top index bit; KEEP bit1 in the tag so the mapping
    // remains injective across halfwords and aliases. Same RAM/tag width.
    def index(pc: UInt): UInt = if (p.withC && p.fpgaTimingCuts)
        pc(indexBits + 1, 2) ^ Mux(pc(1), (BigInt(1) << (indexBits - 1)).U(indexBits.W), 0.U(indexBits.W))
        else pc(indexBits + alignmentBits - 1, alignmentBits)
    def tag(pc: UInt): UInt = if (p.withC && p.fpgaTimingCuts)
        Cat(pc(p.xlen - 1, indexBits + 2), pc(1)) else pc(p.xlen - 1, indexBits + alignmentBits)
    def row(i: UInt): UInt = i(rowBits - 1, 0)
    def bank(i: UInt): UInt = if (bankCount == 1) 0.U else i(indexBits - 1, rowBits)
    val lookupIndex = index(io.pc)
    val lookups = entries.map(_.read(row(lookupIndex)))
    val hits = lookups.zipWithIndex.map { case (entry, b) =>
        bank(lookupIndex) === b.U && valid((b + 1) * bankRows - 1, b * bankRows)(row(lookupIndex)) &&
            (if (p.fpgaTimingCuts) I1TimingMath.equal(entry.tag, tag(io.pc)) else entry.tag === tag(io.pc))
    }
    io.hit := hits.reduce(_ || _)
    // Prepare both fixed increments before RAM hit/length arrives. No late
    // variable addend/carry-in through a full XLEN PC feedback chain.
    val plusTwo = if (p.fpgaTimingCuts) I1TimingMath.incrementPowerOfTwo(io.pc, 1) else io.pc + 2.U
    val plusFour = if (p.fpgaTimingCuts) I1TimingMath.incrementPowerOfTwo(io.pc, 2) else io.pc + 4.U
    val takeTargets = lookups.zip(hits).map { case (entry, hit) =>
        hit && entry.controlFlow && (!entry.conditional || entry.counter(1))
    }
    val takeTarget = takeTargets.reduce(_ || _)
    val shortSequential = p.withC.B && lookups.zip(hits).map { case (entry, hit) =>
        hit && entry.compressed
    }.reduce(_ || _)
    // Resolve bank-local permission/direction in parallel; do not first
    // select the whole Entry, then compare its tag, then choose the target.
    io.nextPc := Mux1H(Seq((!takeTarget && shortSequential) -> plusTwo,
        (!takeTarget && !shortSequential) -> plusFour) ++
        takeTargets.zip(lookups.map(_.target)))
    val trainingIndex = index(io.train.bits.pc)
    val trainingEntry = Mux1H(entries.zipWithIndex.map { case (memory, b) =>
        (bank(trainingIndex) === b.U) -> memory.read(row(trainingIndex))
    })
    val oldHit = valid(index(io.train.bits.pc)) && trainingEntry.tag === tag(io.train.bits.pc)
    val updated = Wire(new Entry)
    updated.tag := tag(io.train.bits.pc)
    updated.target := io.train.bits.target
    updated.conditional := io.train.bits.conditional
    updated.controlFlow := io.train.bits.controlFlow
    updated.compressed := p.withC.B && io.train.bits.compressed
    updated.counter := Mux(!oldHit, Mux(io.train.bits.taken, 2.U, 1.U),
        Mux(io.train.bits.taken, Mux(trainingEntry.counter === 3.U, 3.U, trainingEntry.counter + 1.U),
            Mux(trainingEntry.counter === 0.U, 0.U, trainingEntry.counter - 1.U)))
    when(io.train.valid) {
        when(io.train.bits.controlFlow || p.withC.B) {
            for ((memory, b) <- entries.zipWithIndex) {
                when(bank(trainingIndex) === b.U) { memory.write(row(trainingIndex), updated) }
            }
            valid := valid | UIntToOH(index(io.train.bits.pc), p.branchPredictorEntries)
        }.elsewhen(oldHit) {
            valid := valid & ~UIntToOH(index(io.train.bits.pc), p.branchPredictorEntries)
        }
    }
    when(io.invalidate) { valid := 0.U }
}
