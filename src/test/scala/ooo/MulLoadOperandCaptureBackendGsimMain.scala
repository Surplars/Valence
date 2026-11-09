package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.MulLoadOperandCaptureBackendGsim

object MulLoadOperandCaptureBackendGsimMain extends App {
    require((args.length == 2 || (args.length == 3 && args(2) == "combined-storage")) &&
        Set("off", "on").contains(args(1)), "output-dir off|on [combined-storage]")
    ChiselStage.emitCHIRRTLFile(new MulLoadOperandCaptureBackendGsim(args(1) == "on", args.length == 3),
        Array("--target-dir", args(0)))
}
