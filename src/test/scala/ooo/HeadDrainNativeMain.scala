package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Real production top and external ports; no observation taps or fixture logic. */
object HeadDrainNativeMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)))
    val params = if (args(1) == "on") HeadDrainTestProfile.on else HeadDrainTestProfile.off
    ChiselStage.emitCHIRRTLFile(new IntegerBackend(params,
        registerCanonicalStoreEvent = params.registeredCanonicalStoreEvent),
        Array("--target-dir", args(0)))
    HeadDrainTestProfile.writeParameters(args(0))
}
