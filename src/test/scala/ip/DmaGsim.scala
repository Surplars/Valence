package ip

import _root_.circt.stage.ChiselStage
import soc.ip.dma.MemoryCopyDma

object DmaGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MemoryCopyDma(
        ramBase = args.lift(1).map(BigInt(_)).getOrElse(BigInt("80010000", 16)),
        ramBytes = args.lift(2).map(BigInt(_)).getOrElse(BigInt(4096))),
        Array("--target-dir", args.head))
}
