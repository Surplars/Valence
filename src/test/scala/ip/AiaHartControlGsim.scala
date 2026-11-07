package ip

import _root_.circt.stage.ChiselStage
import soc.core.ooo.AiaHartControl

/** Focused hart-local control fixture. No executing CPU or instruction-level trap claim. */
object AiaHartControlGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new AiaHartControl, Array("--target-dir", args(0)))
}
