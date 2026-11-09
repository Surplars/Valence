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
        val acceptedFetchValid = Output(Bool())
        val acceptedFetchPc = Output(UInt(p.xlen.W))
        val acceptedFetchPrediction = Output(UInt(p.xlen.W))
        val fetchResponseValid = Output(Bool())
        val fetchResponseInstruction = Output(UInt(32.W))
        val fetchResponseError = Output(Bool())
        val fetchResponsePageFault = Output(Bool())
        val lengthRepairValid = Output(Bool())
        val lengthRepairPc = Output(UInt(p.xlen.W))
        val lengthRepairPrediction = Output(UInt(p.xlen.W))
        val lengthRepairNextPc = Output(UInt(p.xlen.W))
    })
    observation.retiredPrediction := observedRetirementPrediction
    val (valid, pc, predicted, next) = observedBranchResolution
    observation.resolveValid := valid
    observation.resolvePc := pc
    observation.resolvePrediction := predicted
    observation.resolveNextPc := next
    // Capture actual transfer edges, including the first fetch after reset.
    // All fields share one observation edge; there is no production pipeline
    // stage or CE. The C++ ledger never seeds an owner from an assumed reset PC.
    observation.acceptedFetchValid := RegNext(io.instructionRequest.fire, false.B)
    observation.acceptedFetchPc := RegNext(io.instructionRequest.bits)
    observation.acceptedFetchPrediction := RegNext(predictedNext)
    observation.fetchResponseValid := RegNext(io.instructionResponse.fire, false.B)
    observation.fetchResponseInstruction := RegNext(io.instructionResponse.bits.instruction)
    observation.fetchResponseError := RegNext(io.instructionResponse.bits.error)
    observation.fetchResponsePageFault := RegNext(io.instructionResponse.bits.pageFault)
    val (lengthValid, lengthPc, lengthPrediction, lengthNext) = observedFetchLengthRepair
    observation.lengthRepairValid := RegNext(lengthValid, false.B)
    observation.lengthRepairPc := RegNext(lengthPc)
    observation.lengthRepairPrediction := RegNext(lengthPrediction)
    observation.lengthRepairNextPc := RegNext(lengthNext)
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
