package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.AddressLocalityPairGsim

object AddressLocalityPairGsimMain extends App {
    require(args.length == 1, "usage: AddressLocalityPairGsimMain <target-dir>")
    ChiselStage.emitCHIRRTLFile(new AddressLocalityPairGsim, Array("--target-dir", args.head))
}
