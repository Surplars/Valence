package inorder
import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.inorder.I1TimingMath

class I1IncrementTimingFixture(width: Int) extends Module {
    val io = IO(new Bundle {
        val pc = Input(UInt(width.W))
        val plusTwo = Output(UInt(width.W))
        val plusFour = Output(UInt(width.W))
    })
    io.plusTwo := I1TimingMath.incrementPowerOfTwo(io.pc, 1)
    io.plusFour := I1TimingMath.incrementPowerOfTwo(io.pc, 2)
}
object I1IncrementTimingMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1IncrementTimingFixture(args(1).toInt),
        Array("--target-dir", args.head))
}
