package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.inorder._

/** Observation exists only in this test top. Expectations remain in the independent C++ ISA oracle. */
class I1PerformanceCore(p: FiveStageConfig) extends FiveStageCore(p) {
    val observation = IO(new Bundle {
        val retiredPrediction = Output(UInt(p.xlen.W))
        val resolveValid = Output(Bool())
        val resolvePc = Output(UInt(p.xlen.W))
        val resolvePrediction = Output(UInt(p.xlen.W))
        val resolveNextPc = Output(UInt(p.xlen.W))
    })
    observation.retiredPrediction := observedRetirementPrediction
    val (valid, pc, predicted, next) = observedBranchResolution
    observation.resolveValid := valid
    observation.resolvePc := pc
    observation.resolvePrediction := predicted
    observation.resolveNextPc := next
}

object I1PerformanceCoreMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1PerformanceCore(FiveStageArguments.config(args)),
        Array("--target-dir", args.head))
}

/** Same cache/translation wiring as production, with only the test CPU observation ports added. */
class I1PerformanceCachedCore(p: FiveStageConfig) extends FiveStageCachedCore(p) {
    override protected def instantiateCore(config: FiveStageConfig, quiesce: Boolean): FiveStageCore = {
        require(!quiesce, "performance fixture uses normal architectural execution")
        new I1PerformanceCore(config)
    }
    private val observedCore = core.asInstanceOf[I1PerformanceCore]
    val observation = IO(chiselTypeOf(observedCore.observation))
    observation := observedCore.observation
}

object I1PerformanceCachedMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1PerformanceCachedCore(FiveStageArguments.config(args)),
        Array("--target-dir", args.head))
}
