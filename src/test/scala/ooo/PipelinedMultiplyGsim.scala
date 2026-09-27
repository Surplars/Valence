package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class PipelinedMultiplyGsim extends Module {
    val p  = OooParams()
    val io = IO(new Bundle {
        val start      = Flipped(Decoupled(new MultiplyDivideRequest(p)))
        val complete   = Decoupled(new BackendCompletion(p))
        val cancelMask = Input(UInt(8.W))
        val liveMask   = Output(UInt(8.W))
        val busy       = Output(Bool())
    })
    val unit = Module(new PipelinedMultiply(p))
    unit.io.start <> io.start
    io.complete <> unit.io.complete
    unit.io.cancel := io.cancelMask.asBools
    io.liveMask    := unit.io.live.asUInt
    io.busy        := unit.io.busy
}
object PipelinedMultiplyGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PipelinedMultiplyGsim, Array("--target-dir", args.head))
}
