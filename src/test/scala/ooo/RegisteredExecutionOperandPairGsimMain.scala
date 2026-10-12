package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.RegisteredExecutionOperandPairGsim

object RegisteredExecutionOperandPairGsimMain extends App {
    require(args.length == 1, "usage: RegisteredExecutionOperandPairGsimMain <target-dir>")
    ChiselStage.emitCHIRRTLFile(new RegisteredExecutionOperandPairGsim, Array("--target-dir", args.head))
}
