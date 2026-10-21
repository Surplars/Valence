package ip

import _root_.circt.stage.ChiselStage
import soc.ip.dma.EthernetPacketDma

/** Real packet DMA, shortened frame storage; production control/credit/owner logic. */
object PacketDmaControlBatchMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new EthernetPacketDma(ramBytes = 65536,
        maxFrameBytes = 64, postedRxSlots = 4, memoryCredits = 4),
        Array("--target-dir", args.head),
        Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info",
            "-default-layer-specialization=disable"))
}
