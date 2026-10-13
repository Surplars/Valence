package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._

object HeadDrainDecodeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new HeadDrainDecodeGsim, Array("--target-dir", args.head))
}
object HeadDrainBackendPairGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new HeadDrainBackendPairGsim, Array("--target-dir", args.head))
    HeadDrainTestProfile.writeParameters(args.head)
}
