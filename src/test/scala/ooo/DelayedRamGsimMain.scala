package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.SynchronousDataRam

object DelayedRamGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(
        new SynchronousDataRam(responseDelay = 5, delayedResponses = 2,
            readLatency = args.lift(1).map(_.toInt).getOrElse(1)),
        Array("--target-dir", args.head)
    )
}
