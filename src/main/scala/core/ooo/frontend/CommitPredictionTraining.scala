package soc.core.ooo

import chisel3._
import chisel3.util._

/** Raw retirement metadata, before instruction classification or next-PC comparison. */
class PredictionTrainingCommit extends Bundle {
    val pc = UInt(64.W)
    val nextPc = UInt(64.W)
    val instruction = UInt(32.W)
}

/** Optional one-cycle predictor-only boundary. Capacity one full retirement
  * packet, II=1, no backpressure; every lane is captured each cycle. Only valid
  * committed lanes authorize training. Reset cancels the pending packet.
  * Architectural retirement, redirect and the retirement RAS are not delayed.
  * Same-index lane order is retained for the predictors' existing ordered folds.
  */
class CommitPredictionTraining(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val committed = Input(Vec(p.commitWidth, Valid(new PredictionTrainingCommit)))
        val branch = Output(Vec(p.commitWidth, Valid(new BranchTraining)))
        val indirect = Output(Vec(p.commitWidth, Valid(new IndirectTargetTraining)))
    })
    val packet = if (p.registeredPredictionTraining) {
        val payload = Reg(Vec(p.commitWidth, new PredictionTrainingCommit))
        val valid = RegNext(VecInit(io.committed.map(_.valid)), VecInit(Seq.fill(p.commitWidth)(false.B)))
        // Unconditional payload capture keeps late valid off a wide register CE.
        payload := VecInit(io.committed.map(_.bits))
        val previous = Wire(Vec(p.commitWidth, Valid(new PredictionTrainingCommit)))
        for (lane <- 0 until p.commitWidth) {
            previous(lane).valid := valid(lane)
            previous(lane).bits := payload(lane)
        }
        previous
    } else io.committed
    for (lane <- 0 until p.commitWidth) {
        val commit = packet(lane)
        val inst = commit.bits.instruction
        val compressedBranch = p.compressedInstructions.B && inst(1, 0) === 1.U &&
            (inst(15, 13) === 6.U || inst(15, 13) === 7.U)
        io.branch(lane).valid := commit.valid && (inst(6, 0) === "h63".U || compressedBranch)
        io.branch(lane).bits.pc := commit.bits.pc
        io.branch(lane).bits.taken := commit.bits.nextPc =/= commit.bits.pc +
            Mux(p.compressedInstructions.B && inst(1, 0) =/= 3.U, 2.U, 4.U)
        val compressedJalr = p.compressedInstructions.B && inst(1, 0) === 2.U &&
            inst(15, 13) === 4.U && inst(6, 2) === 0.U && inst(11, 7) =/= 0.U
        val regularJalr = inst(6, 0) === "h67".U && inst(14, 12) === 0.U && inst(1, 0) === 3.U
        io.indirect(lane).valid := commit.valid && (regularJalr || compressedJalr)
        io.indirect(lane).bits.pc := commit.bits.pc
        io.indirect(lane).bits.target := commit.bits.nextPc
    }
}
