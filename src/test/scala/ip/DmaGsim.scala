package ip

import _root_.circt.stage.ChiselStage
import soc.ip.dma.MemoryCopyDma

object DmaGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MemoryCopyDma(), Array("--target-dir", args.head))
}
