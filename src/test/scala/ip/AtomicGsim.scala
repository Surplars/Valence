package ip

import _root_.circt.stage.ChiselStage
import soc.ip.memory.AtomicMemory

object AtomicGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new AtomicMemory(
        bytes = if (args.length > 1) args(1).toInt else 4096,
        registerResponseOwners = args.contains("registered-owners")
    ),
        Array("--target-dir", args.head))
}
object AtomicRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new AtomicMemory(registerResponseOwners = args.contains("registered-owners")),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
