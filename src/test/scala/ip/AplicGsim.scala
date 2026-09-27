package ip

import _root_.circt.stage.ChiselStage
import soc.ip.interrupt._

object AplicGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new Aplic(AplicParams(sources = args(1).toInt)), Array("--target-dir", args.head))
}
object AplicRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new Aplic(),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
