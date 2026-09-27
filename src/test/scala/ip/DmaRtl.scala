package ip

import _root_.circt.stage.ChiselStage
import soc.ip.dma.MemoryCopyDma

object DmaRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new MemoryCopyDma(),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
