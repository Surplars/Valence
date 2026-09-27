package ip

import _root_.circt.stage.ChiselStage
import soc.ip.timer.MachineTimer

object TimerGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MachineTimer(), Array("--target-dir", args.head))
}
object TimerRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new MachineTimer(),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
