package debug

import _root_.circt.stage.ChiselStage
import soc.core.ooo.DmaRegisterDataAdapter

object JtagDmaLaneGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DmaRegisterDataAdapter, Array("--target-dir", args.head))
}
