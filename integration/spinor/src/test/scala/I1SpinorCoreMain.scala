package spinor_integration

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._

/** Actual transfer observations for the same-clock functional fixture only. */
class I1SpinorCoreFixture(p: FiveStageConfig) extends I1SpinorSameClockBringup(p) {
    override def desiredName = "I1SpinorCoreFixture"
    val observation = IO(new Bundle {
        val retire = Valid(new FiveStageRetire(p))
        val vectorOffer = Valid(new I1SpinorCommand)
        val vectorDone = Output(Bool())
    })
    // Sample real transfer edges, avoiding NEXT-state combinational capacity.
    observation.retire := RegNext(cpu.io.retire, 0.U.asTypeOf(Valid(new FiveStageRetire(p))))
    observation.vectorOffer.valid := RegNext(host.command.fire, false.B)
    observation.vectorOffer.bits := RegNext(host.command.bits)
    observation.vectorDone := RegNext(host.done.fire, false.B)
}

object I1SpinorCoreMain extends App {
    val p = FiveStageConfig(withA = true, withC = true, withF = true, withD = true,
        multiplyMode = "dsp-tiled", pipelineProfile = "fpga8", fpgaTimingCuts = true,
        instructionCacheBytes = 32768, dataCacheBytes = 32768, branchPredictorEntries = 128,
        hartId = 0xbeef, spinor = true)
    ChiselStage.emitCHIRRTLFile(new I1SpinorCoreFixture(p), Array("--target-dir", args.head))
}
