package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._

/** One input/output capture edge gives both predictor versions the same synchronous context.
  * The production predictor stays combinational, accepts one training event per cycle,
  * has no request queue, and invalidates all valid metadata at the active edge.
  */
class I1PredictionTimingTop(p: FiveStageConfig) extends Module {
    val io = IO(new Bundle {
        val pc = Input(UInt(p.xlen.W))
        val training = Flipped(Valid(new FiveStageBranchTraining(p)))
        val invalidate = Input(Bool())
        val nextPc = Output(UInt(p.xlen.W))
        val hit = Output(Bool())
    })
    val predictor = Module(new FiveStageBranchPredictor(p))
    val lookupPc = RegNext(io.pc)
    val trainingValid = RegNext(io.training.valid, false.B)
    val trainingBits = RegNext(io.training.bits)
    val invalidate = RegNext(io.invalidate, false.B)
    predictor.io.pc := lookupPc
    predictor.io.train.valid := trainingValid
    predictor.io.train.bits := trainingBits
    predictor.io.invalidate := invalidate
    io.nextPc := RegNext(predictor.io.nextPc)
    io.hit := RegNext(predictor.io.hit)
}

object I1PredictionTimingMain extends App {
    ChiselStage.emitSystemVerilogFile(new I1PredictionTimingTop(FiveStageArguments.config(args)),
        Array("--target-dir", args.head),
        Array("--split-verilog", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
