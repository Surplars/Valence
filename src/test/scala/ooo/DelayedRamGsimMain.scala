package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.SynchronousDataRam

object DelayedRamGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(
        new SynchronousDataRam(responseDelay = 5, delayedResponses = 2),
        Array("--target-dir", args.head)
    )
}
