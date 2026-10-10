package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Only the local response-buffer empty-flow option differs between the paired fixtures. */
class TranslatedResponseFlowGsim(enabled: Boolean) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val idle = Output(Bool())
    })
    val buffer = Module(new DataResponseBuffer(registerPayload = true, registerHead = true, emptyFlow = enabled))
    buffer.io.upstream <> io.upstream
    io.downstream <> buffer.io.downstream
    io.idle := buffer.io.idle
}

object TranslatedResponseFlowGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)), "output-directory and 0|1 required")
    ChiselStage.emitCHIRRTLFile(new TranslatedResponseFlowGsim(args(1) == "1"), Array("--target-dir", args(0)))
}
