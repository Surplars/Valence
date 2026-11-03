package inorder

import chisel3._
import chisel3.reflect.DataMirror
import _root_.circt.stage.ChiselStage
import soc.core.inorder._

/** Complete cached CPU with one capture register at EVERY data/control port boundary.
  * This is a timing context, not an elastic adapter or extra architectural CPU stage.
  * Functional software simulation uses the unwrapped production CPU separately.
  */
class I1Core300Context(p: FiveStageConfig) extends Module {
    val cpu = Module(new FiveStageCachedCore(p))
    val io = IO(chiselTypeOf(cpu.io))
    val coreReset = RegNext(reset.asBool, true.B)
    cpu.reset := coreReset
    def capture(internal: Data, external: Data): Unit = (internal, external) match {
        case (a: Record, b: Record) => a.elements.foreach { case (name, value) => capture(value, b.elements(name)) }
        case (a: Vec[_], b: Vec[_]) => a.getElements.zip(b.getElements).foreach { case (x, y) => capture(x, y) }
        case (a, b) => DataMirror.directionOf(a) match {
            case ActualDirection.Input => a := RegNext(b)
            case ActualDirection.Output => b := RegNext(a)
            case direction => throw new IllegalArgumentException(s"unsupported timing port direction $direction")
        }
    }
    capture(cpu.io, io)
}

// Lower masked RAMs to ground byte memories before deduplication. Keeping aggregate
// RAMs permits differing I/D write-mask granularities to alias in firtool 1.135.0.
object I1Core300Main extends App {
    ChiselStage.emitSystemVerilogFile(new I1Core300Context(FiveStageArguments.config(args)),
        Array("--target-dir", args.head),
        Array("--split-verilog", "--lower-memories", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
