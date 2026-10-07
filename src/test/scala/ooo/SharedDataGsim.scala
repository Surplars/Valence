package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo.{DataPort, SharedDataArbiter}

class SharedDataGsim(registerResponseOwners: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val client0 = Flipped(new DataPort)
        val client1 = Flipped(new DataPort)
        val memory  = new DataPort
    })
    val arbiter = Module(new SharedDataArbiter(registerResponseOwners))
    io.client0 <> arbiter.io.clients(0)
    io.client1 <> arbiter.io.clients(1)
    io.memory <> arbiter.io.memory
}
object SharedDataGsimMain extends App {
    require(args.drop(1).forall(Set("registered-owners", "rtl").contains))
    val module = () => new SharedDataGsim(args.drop(1).contains("registered-owners"))
    if (args.drop(1).contains("rtl")) {
        ChiselStage.emitSystemVerilogFile(module(), Array("--target-dir", args.head),
            Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
    } else ChiselStage.emitCHIRRTLFile(module(), Array("--target-dir", args.head))
}
