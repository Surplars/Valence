package ip

import _root_.circt.stage.ChiselStage
import soc.ip.interrupt._

object ImsicGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(
        new Imsic(ImsicParams(identities = args(1).toInt, guestFiles = args(2).toInt)),
        Array("--target-dir", args.head)
    )
}
object ImsicRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new Imsic(),
        Array("--target-dir", args.head),
        firtoolOpts = Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
