package spinor_integration

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder.{FiveStageConfig, I1SpinorCommand}
import soc.integration.spinor.I1SpinorDualClockCore

class I1SpinorDualClockFixture(p: FiveStageConfig) extends I1SpinorDualClockCore(p) {
    val observation = IO(new Bundle {
        val vectorOffer = Valid(new I1SpinorCommand)
        val vectorDone = Output(Bool())
    })
    observation.vectorOffer.valid := cpu.io.spinor.get.command.fire
    observation.vectorOffer.bits := cpu.io.spinor.get.command.bits
    observation.vectorDone := cpu.io.spinor.get.done.fire
}

object I1SpinorDualClockMain extends App {
    val p = FiveStageConfig(withA = true, withC = true, withF = true, withD = true,
        multiplyMode = "dsp-tiled", pipelineProfile = "fpga8", fpgaTimingCuts = true,
        instructionCacheBytes = 32768, dataCacheBytes = 32768, branchPredictorEntries = 128,
        hartId = 0xbeef, spinor = true)
    if (args.contains("--sv")) ChiselStage.emitSystemVerilogFile(new I1SpinorDualClockCore(p),
        Array("--target-dir", args.head),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
    else if (args.contains("--observe"))
        ChiselStage.emitCHIRRTLFile(new I1SpinorDualClockFixture(p), Array("--target-dir", args.head))
    else ChiselStage.emitCHIRRTLFile(new I1SpinorDualClockCore(p), Array("--target-dir", args.head))
}
