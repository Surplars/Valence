package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._

/** Independent numerical fixture, not an architectural-state substitute. */
class I1FloatingPointGsim(double: Boolean, timingCuts: Boolean = false) extends Module {
    val p = FiveStageConfig(withF = true, withD = double,
        pipelineProfile = if (timingCuts) "fpga8" else "compact5", fpgaTimingCuts = timingCuts)
    val io = IO(new Bundle {
        val flush = Input(Bool())
        val request = Flipped(Decoupled(new Bundle {
            val a = UInt(64.W); val b = UInt(64.W); val c = UInt(64.W)
            val integer = UInt(64.W); val instruction = UInt(32.W)
            val rounding = UInt(3.W); val token = new I1FloatingPointToken
        }))
        val result = Decoupled(new I1FloatingPointResult(p))
        val completed = Output(Bool())
    })
    val execute = Module(new I1FloatingPointExecute(p, p.floatingConfig))
    execute.io.flush := io.flush
    execute.io.request.valid := io.request.valid; io.request.ready := execute.io.request.ready
    execute.io.request.bits := 0.U.asTypeOf(new I1FloatingPointExecution(p))
    execute.io.request.bits.command.token := io.request.bits.token
    execute.io.request.bits.command.instruction := io.request.bits.instruction
    execute.io.request.bits.command.integerSource := io.request.bits.integer
    execute.io.request.bits.operands := VecInit(Seq(io.request.bits.a, io.request.bits.b, io.request.bits.c))
    execute.io.request.bits.rounding := io.request.bits.rounding
    io.result <> execute.io.result
    io.completed := execute.io.completed
}
object I1FloatingPointMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1FloatingPointGsim(args.contains("--d"), args.contains("--timing-cuts")),
        Array("--target-dir", args.head))
}
class I1FloatingPointCompressedGsim extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(16.W)); val expanded = Output(UInt(32.W))
        val legal = Output(Bool()); val disabledLegal = Output(Bool())
    })
    val enabled = Module(new FiveStageCompressed(64, withF = true, withD = true))
    val disabled = Module(new FiveStageCompressed(64))
    enabled.io.instruction := io.instruction; disabled.io.instruction := io.instruction
    io.expanded := enabled.io.expanded; io.legal := enabled.io.legal; io.disabledLegal := disabled.io.legal
}
object I1FloatingPointCompressedMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1FloatingPointCompressedGsim, Array("--target-dir", args.head))
}
object FiveStageFpgaShellRtlMain extends App {
    val chain = args.find(_.startsWith("--soc-user-chain="))
        .map(_.stripPrefix("--soc-user-chain=").toInt).getOrElse(0)
    val p = FiveStageSocArguments.config(I1BscanArguments.removeScanBits(args).filterNot(_.startsWith("--soc-user-chain=")))
    ChiselStage.emitSystemVerilogFile(new FiveStageFpgaShell(p, chain, I1BscanArguments.scanBits(args)), Array("--target-dir", args.head),
        Array("--split-verilog", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
