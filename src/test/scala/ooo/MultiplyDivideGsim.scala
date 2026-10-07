package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._

object MultiplyDivideGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MultiplyDivide(OooParams(
        registeredMulDivOperands = args.lift(1).contains("registered"))), Array("--target-dir", args.head))
}
