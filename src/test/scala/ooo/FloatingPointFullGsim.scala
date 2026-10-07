package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Direct numerical producer fixture: no synthetic architectural-state claims. */
class FloatingPointFullGsim(c: FloatingPointConfig) extends Module {
    val p = OooParams(robEntries = 16, tagBits = 64)
    val io = IO(new Bundle {
        val flush = Input(Bool())
        val request = Flipped(Decoupled(new Bundle {
            val a = UInt(64.W); val b = UInt(64.W); val c = UInt(64.W)
            val integer = UInt(64.W); val instruction = UInt(32.W)
            val rounding = UInt(3.W); val token = new RobToken(p)
        }))
        val result = Decoupled(new FloatingPointResult(p))
    })
    val execute = Module(new FloatingPointExecute(p, c))
    execute.io.flush := io.flush
    execute.io.request.valid := io.request.valid
    io.request.ready := execute.io.request.ready
    execute.io.request.bits := 0.U.asTypeOf(new FloatingPointExecution(p))
    execute.io.request.bits.command.token := io.request.bits.token
    execute.io.request.bits.command.instruction := io.request.bits.instruction
    execute.io.request.bits.command.integerSource := io.request.bits.integer
    execute.io.request.bits.operands := VecInit(Seq(io.request.bits.a, io.request.bits.b, io.request.bits.c))
    execute.io.request.bits.rounding := io.request.bits.rounding
    io.result <> execute.io.result
}
object FloatingPointFullGsimMain extends App {
    val c = args.lift(1).getOrElse("fd") match {
        case "fd" => FloatingPointConfig.fullFD
        case "f" => FloatingPointConfig.fullF
        case "small" => FloatingPointConfig.fullF.copy(multiply = false, divide = false,
            squareRoot = false, fusedMultiplyAdd = false, conversions = false)
    }
    ChiselStage.emitCHIRRTLFile(new FloatingPointFullGsim(c), Array("--target-dir", args.head))
}
object FloatingPointFullCpuGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FloatingPointCpuGsim(withMemory = true, compressed = true, publishGc = true),
        Array("--target-dir", args.head))
}
class FloatingPointCompressedGsim extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(16.W))
        val expanded = Output(UInt(32.W)); val legal = Output(Bool())
        val disabledLegal = Output(Bool())
    })
    val (expanded, legal) = soc.isa.Compressed.expand(io.instruction, floatingDouble = true)
    val (_, disabled) = soc.isa.Compressed.expand(io.instruction)
    io.expanded := expanded; io.legal := legal; io.disabledLegal := disabled
}
object FloatingPointCompressedGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FloatingPointCompressedGsim, Array("--target-dir", args.head))
}
