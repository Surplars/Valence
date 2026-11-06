package spinor_integration

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.reflect.DataMirror
import soc.core.inorder.FiveStageConfig
import soc.integration.spinor.I1SpinorDualClockCore

/** Complete port-capture context for OOC timing, not an architectural stage.
  * Data/control ports use CPU clock except the VPU-local idle observation.
  * Common cold reset goes directly to the real per-domain reset synchronizers.
  */
class I1Spinor300Context(p: FiveStageConfig) extends RawModule {
    val cpuClock = IO(Input(Clock()))
    val vpuClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val dut = Module(new I1SpinorDualClockCore(p))
    dut.cpuClock := cpuClock; dut.vpuClock := vpuClock; dut.commonColdReset := commonColdReset
    val io = IO(chiselTypeOf(dut.io))
    def capture(internal: Data, external: Data, localClock: Clock): Unit = (internal, external) match {
        case (a: Record, b: Record) =>
            a.elements.foreach { case (name, value) => capture(value, b.elements(name), localClock) }
        case (a: Vec[_], b: Vec[_]) =>
            a.getElements.zip(b.getElements).foreach { case (x, y) => capture(x, y, localClock) }
        case (a, b) => withClock(localClock) {
            DataMirror.directionOf(a) match {
                case ActualDirection.Input => a := RegNext(b)
                case ActualDirection.Output => b := RegNext(a)
                case direction => throw new IllegalArgumentException(s"unsupported timing port direction $direction")
            }
        }
    }
    dut.io.elements.foreach { case (name, port) =>
        capture(port, io.elements(name), if (name == "vpuTransportIdle") vpuClock else cpuClock)
    }
}

object I1Spinor300Main extends App {
    val p = FiveStageConfig(withA = true, withC = true, withF = true, withD = true,
        multiplyMode = "dsp-tiled", pipelineProfile = "fpga8", fpgaTimingCuts = true,
        instructionCacheBytes = 32768, dataCacheBytes = 32768, branchPredictorEntries = 128,
        hartId = 0xbeef, spinor = true)
    ChiselStage.emitSystemVerilogFile(new I1Spinor300Context(p), Array("--target-dir", args.head),
        Array("--split-verilog", "--lower-memories",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
