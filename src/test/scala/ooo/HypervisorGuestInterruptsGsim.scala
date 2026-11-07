package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.HypervisorGuestInterrupts

object HypervisorGuestInterruptsGsimMain extends App {
    require(args.length == 2, "usage: HypervisorGuestInterruptsGsimMain <output> <GEILEN>")
    ChiselStage.emitCHIRRTLFile(new HypervisorGuestInterrupts(args(1).toInt), Array("--target-dir", args(0)))
}
