package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._

object MultiplyDivideGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MultiplyDivide(OooParams()), Array("--target-dir", args.head))
}
