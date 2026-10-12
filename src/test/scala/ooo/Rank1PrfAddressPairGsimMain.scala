package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.Rank1PrfAddressPairGsim

object Rank1PrfAddressPairGsimMain extends App {
    require(args.length == 1, "usage: Rank1PrfAddressPairGsimMain <target-dir>")
    ChiselStage.emitCHIRRTLFile(new Rank1PrfAddressPairGsim, Array("--target-dir", args.head))
}
