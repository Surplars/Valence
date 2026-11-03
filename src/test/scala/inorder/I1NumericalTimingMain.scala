package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._

/** Scalar ports preserve the complete XLEN+1 window in the pinned GSIM interface. */
class I1DivideStepFixture(xlen: Int) extends Module {
    val io = IO(new Bundle {
        val high = Input(Bool())
        val low = Input(UInt(xlen.W))
        val divisor = Input(UInt(xlen.W))
        val quotientBit = Output(Bool())
        val remainderHigh = Output(Bool())
        val remainderLow = Output(UInt(xlen.W))
    })
    val step = Module(new I1RestoringDivideStep(xlen))
    step.io.window := Cat(io.high, io.low)
    step.io.divisor := io.divisor
    io.quotientBit := step.io.quotientBit
    io.remainderHigh := step.io.remainder(xlen)
    io.remainderLow := step.io.remainder(xlen - 1, 0)
}

object I1DivideStepMain extends App {
    require(args.length == 2)
    ChiselStage.emitCHIRRTLFile(new I1DivideStepFixture(args(1).toInt), Array("--target-dir", args.head))
}

object I1MulDivRtlMain extends App {
    val p = FiveStageArguments.config(args)
    ChiselStage.emitSystemVerilogFile(new FiveStageMulDiv(p), Array("--target-dir", args.head),
        Array("--split-verilog", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
