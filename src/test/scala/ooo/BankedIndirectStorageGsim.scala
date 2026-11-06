package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Matched logical-16 component pair. Does not select a production CPU or board profile. */
class BankedIndirectStorageGsim(bankedStorage: Boolean) extends Module {
    val p = OooParams(renameWidth = 2, commitWidth = 2, completionWidth = 2,
        branchPredictorEntries = 32, indirectTargetEntries = 16, compressedInstructions = true,
        registeredPredictionTraining = true)
    val io = IO(new Bundle {
        val retired = Input(new PredictionCommitPorts(2))
        val pc = Input(new OperandScalarPorts(64, 2))
        val taken = Output(new OperandScalarPorts(1, 2))
        val hit = Output(new OperandScalarPorts(1, 2))
        val target = Output(new OperandScalarPorts(64, 2))
    })
    val training = Module(new CommitPredictionTraining(p))
    val branch = Module(new BranchPredictor(p))
    val indirect = Module(new IndirectTargetPredictor(p, bankedStorage = bankedStorage))
    training.io.committed := VecInit((0 until 2).map(io.retired.at))
    branch.io.train := training.io.branch
    indirect.io.train := training.io.indirect
    branch.io.pc := VecInit((0 until 2).map(io.pc.at))
    indirect.io.pc := VecInit((0 until 2).map(io.pc.at))
    for (lane <- 0 until 2) {
        io.taken.at(lane) := branch.io.taken(lane)
        io.hit.at(lane) := indirect.io.hit(lane)
        io.target.at(lane) := indirect.io.target(lane)
    }
}

object BankedIndirectStorageGsimMain extends App {
    require(args.length == 2 && Set("reg", "banked").contains(args(1)),
        "usage: BankedIndirectStorageGsimMain <output> reg|banked")
    ChiselStage.emitCHIRRTLFile(new BankedIndirectStorageGsim(args(1) == "banked"),
        Array("--target-dir", args(0)))
}
