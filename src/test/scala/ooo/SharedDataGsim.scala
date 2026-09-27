package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo.{DataPort, SharedDataArbiter}

class SharedDataGsim extends Module {
    val io = IO(new Bundle {
        val client0 = Flipped(new DataPort)
        val client1 = Flipped(new DataPort)
        val memory  = new DataPort
    })
    val arbiter = Module(new SharedDataArbiter())
    io.client0 <> arbiter.io.clients(0)
    io.client1 <> arbiter.io.clients(1)
    io.memory <> arbiter.io.memory
}
object SharedDataGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new SharedDataGsim(), Array("--target-dir", args.head))
}
