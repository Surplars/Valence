package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import scala.collection.immutable.ListMap

class PredictionCommitPorts(width: Int) extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until width).map(i =>
        s"lane$i" -> Valid(new PredictionTrainingCommit)): _*)
    def at(i: Int): ValidIO[PredictionTrainingCommit] =
        elements(s"lane$i").asInstanceOf[ValidIO[PredictionTrainingCommit]]
}

class PredictionTrainingGsim(width: Int, compressed: Boolean, delayed: Boolean) extends Module {
    val p = OooParams(renameWidth = width, commitWidth = width, completionWidth = width,
        branchPredictorEntries = 32, indirectTargetEntries = 16, compressedInstructions = compressed,
        registeredPredictionTraining = delayed)
    val io = IO(new Bundle {
        val retired = Input(new PredictionCommitPorts(width))
        val pc = Input(new OperandScalarPorts(64, width))
        val taken = Output(new OperandScalarPorts(1, width))
        val hit = Output(new OperandScalarPorts(1, width))
        val target = Output(new OperandScalarPorts(64, width))
    })
    val training = Module(new CommitPredictionTraining(p))
    val branch = Module(new BranchPredictor(p))
    val indirect = Module(new IndirectTargetPredictor(p))
    training.io.committed := VecInit((0 until width).map(io.retired.at))
    branch.io.train := training.io.branch
    indirect.io.train := training.io.indirect
    branch.io.pc := VecInit((0 until width).map(io.pc.at))
    indirect.io.pc := VecInit((0 until width).map(io.pc.at))
    for (lane <- 0 until width) {
        io.taken.at(lane) := branch.io.taken(lane)
        io.hit.at(lane) := indirect.io.hit(lane)
        io.target.at(lane) := indirect.io.target(lane)
    }
}

object PredictionTrainingGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PredictionTrainingGsim(args.lift(1).map(_.toInt).getOrElse(2),
        !args.contains("plain"), !args.contains("direct")), Array("--target-dir", args.head))
}

object ControlHeadsCoreGsimMain extends App {
    val p = BoardSocConfig.timingParams("staged-control-heads").copy(
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096,
        compressedInstructions = false, parallelFetchAlignment = false, parallelFetchTagLookup = false,
        alignedFetchPmp = false, rawFetchPresence = false, parallelReturnStackControl = false,
        parallelPacketPmp = false)
    ChiselStage.emitCHIRRTLFile(new IntegerCoreGsim(p), Array("--target-dir", args.head))
}
