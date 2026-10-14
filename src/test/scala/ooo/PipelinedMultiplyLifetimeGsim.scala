package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class PipelinedMultiplyLifetimeGsim(registered: Boolean = false, bounded: Boolean = false) extends Module {
    val p  = OooParams(robEntries = 16, physicalRegs = 48, tagBits = 64, registeredMulDivOperands = registered)
    val io = IO(new Bundle {
        val start      = Flipped(Decoupled(new MultiplyDivideRequest(p)))
        val complete   = Decoupled(new BackendCompletion(p))
        val cancelMask = Input(UInt(8.W))
        val liveMask   = Output(UInt(8.W))
        val busy       = Output(Bool())
        val owner0 = Output(new RobToken(p))
        val owner1 = Output(new RobToken(p))
        val owner2 = Output(new RobToken(p))
        val owner3 = Output(new RobToken(p))
        val owner4 = Output(new RobToken(p))
        val owner5 = Output(new RobToken(p))
        val owner6 = Output(new RobToken(p))
        val owner7 = Output(new RobToken(p))
        val preview = Output(Valid(new BackendCompletion(p)))
    })
    val unit = Module(new PipelinedMultiply(p, bounded))
    unit.io.start <> io.start
    io.complete <> unit.io.complete
    unit.io.cancel := io.cancelMask.asBools
    io.liveMask    := unit.io.live.asUInt
    io.busy        := unit.io.busy
    io.preview := unit.io.wordPreview
    io.owner0 := unit.io.owner(0)
    io.owner1 := unit.io.owner(1)
    io.owner2 := unit.io.owner(2)
    io.owner3 := unit.io.owner(3)
    io.owner4 := unit.io.owner(4)
    io.owner5 := unit.io.owner(5)
    io.owner6 := unit.io.owner(6)
    io.owner7 := unit.io.owner(7)
}
object PipelinedMultiplyLifetimeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PipelinedMultiplyLifetimeGsim(args.lift(1).contains("registered"), args.lift(2).contains("bounded")), Array("--target-dir", args.head))
}
