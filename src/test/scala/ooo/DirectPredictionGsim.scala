package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo.DirectPredictionQualification

class DirectPredictionGsim extends Module {
    val io = IO(new Bundle {
        val pc = Input(UInt(64.W))
        val immediate = Input(UInt(64.W))
        val shortInstruction = Input(Bool())
        val aligned16 = Output(Bool())
        val aligned32 = Output(Bool())
        val differentSuccessor = Output(Bool())
    })
    val guard = Module(new DirectPredictionQualification)
    guard.io.pcLow := io.pc(1, 0)
    guard.io.immediate := io.immediate
    guard.io.shortInstruction := io.shortInstruction
    io.aligned16 := guard.io.aligned16
    io.aligned32 := guard.io.aligned32
    io.differentSuccessor := guard.io.differentSuccessor
}

object DirectPredictionGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DirectPredictionGsim, Array("--target-dir", args.head))
}
