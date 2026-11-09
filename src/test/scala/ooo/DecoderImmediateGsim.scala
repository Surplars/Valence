package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
import soc.isa.Compressed

/** Exercise the actual full-feature decode producer of the compact issue payload contract. */
class DecoderImmediateGsim extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val compressed = Input(Bool())
        val immediate = Output(UInt(64.W))
    })
    val (expanded, legal) = Compressed.expand(io.instruction(15, 0), floatingDouble = true)
    val decoder = Module(new IntegerDecode(enableSystem = true, enableAtomic = true,
        experimentalFloatingPoint = true))
    decoder.io.instruction := Mux(io.compressed, Mux(legal, expanded, 0.U), io.instruction)
    decoder.io.pc := "h80000000".U
    io.immediate := decoder.io.decoded.immediate
}
object DecoderImmediateGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DecoderImmediateGsim, Array("--target-dir", args.head))
}
