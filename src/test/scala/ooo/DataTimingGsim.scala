package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** The request/response credit contracts used by the staged-data profile. */
class DataTimingGsim(registerPayload: Boolean = false, registerHead: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
    })
    val requests = Module(new DataRequestBuffer)
    val responses = Module(new DataResponseBuffer(registerPayload, registerHead))
    requests.io.requestCpu := true.B
    requests.io.upstream <> io.upstream
    responses.io.upstream <> requests.io.downstream
    io.downstream <> responses.io.downstream
}

object DataTimingGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DataTimingGsim(args.drop(1).contains("registered-payload"),
        args.drop(1).contains("register-head")),
        Array("--target-dir", args.head))
}
