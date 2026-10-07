package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class FloatingPointAddGsim extends Module {
    private val p = OooParams(robEntries = 16, tagBits = 64)
    val io = IO(new Bundle {
        val flush = Input(Bool())
        val request = Flipped(Decoupled(new Bundle {
            val a = UInt(64.W)
            val b = UInt(64.W)
            val instruction = UInt(32.W)
            val rounding = UInt(3.W)
            val token = new RobToken(p)
        }))
        val result = Decoupled(new FloatingPointResult(p))
    })
    val add = Module(new FloatingPointAdd(p))
    add.io.flush := io.flush
    add.io.request.valid := io.request.valid
    io.request.ready := add.io.request.ready
    add.io.request.bits := 0.U.asTypeOf(new FloatingPointExecution(p))
    add.io.request.bits.command.token := io.request.bits.token
    add.io.request.bits.command.instruction := io.request.bits.instruction
    add.io.request.bits.operands(0) := io.request.bits.a
    add.io.request.bits.operands(1) := io.request.bits.b
    add.io.request.bits.rounding := io.request.bits.rounding
    io.result <> add.io.result
}

object FloatingPointAddGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FloatingPointAddGsim, Array("--target-dir", args.head))
}

object FloatingPointAddStateGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FloatingPointAddStateGsim, Array("--target-dir", args.head))
}
