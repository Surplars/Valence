package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class BranchPredictor256Gsim extends Module {
    val io = IO(new Bundle {
        val pc0    = Input(UInt(64.W))
        val pc1    = Input(UInt(64.W))
        val taken0 = Output(Bool())
        val taken1 = Output(Bool())
        val train0 = Input(Valid(new BranchTraining))
        val train1 = Input(Valid(new BranchTraining))
    })
    val predictor = Module(new BranchPredictor(OooParams(
        renameWidth = 2, commitWidth = 2, branchPredictorEntries = 256, compressedInstructions = true
    )))
    predictor.io.pc(0)    := io.pc0
    predictor.io.pc(1)    := io.pc1
    predictor.io.train(0) := io.train0
    predictor.io.train(1) := io.train1
    io.taken0             := predictor.io.taken(0)
    io.taken1             := predictor.io.taken(1)
}
object BranchPredictor256GsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new BranchPredictor256Gsim, Array("--target-dir", args.head))
}
