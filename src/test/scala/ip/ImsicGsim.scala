package ip

import _root_.circt.stage.ChiselStage
import soc.ip.interrupt._

object ImsicGsimMain extends App {
    require(args.length == 3 || args.length == 5)
    val machineBase = if (args.length == 5) BigInt(args(3), 16) else BigInt("24000000", 16)
    val supervisorBase = if (args.length == 5) BigInt(args(4), 16) else BigInt("28000000", 16)
    ChiselStage.emitCHIRRTLFile(
        new Imsic(ImsicParams(identities = args(1).toInt, guestFiles = args(2).toInt,
            machineBase = machineBase, supervisorBase = supervisorBase)),
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
