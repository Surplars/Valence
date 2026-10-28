package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.MulLoadOperandCaptureBackendGsim

object MulLoadOperandCaptureBackendGsimMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)), "output-dir off|on")
    ChiselStage.emitCHIRRTLFile(new MulLoadOperandCaptureBackendGsim(args(1) == "on"),
        Array("--target-dir", args(0)))
}
