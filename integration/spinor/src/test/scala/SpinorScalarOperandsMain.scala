package spinor_integration

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.integration.spinor.SpinorScalarOperands
import vpu.Command

/** Raw scalar inputs for independent native-ABI GSIM checks; not a CPU execution top. */
class SpinorScalarOperandsFixture extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val integerLeft = Input(UInt(64.W))
        val integerRight = Input(UInt(64.W))
        val floatingLeft = Input(UInt(64.W))
        val token = Input(UInt(80.W))
        val command = Output(new Command)
    })
    io.command := SpinorScalarOperands(io.instruction, io.integerLeft, io.integerRight, io.floatingLeft, io.token)
}

object SpinorScalarOperandsMain extends App {
    ChiselStage.emitCHIRRTLFile(new SpinorScalarOperandsFixture, Array("--target-dir", args.head))
}
