package inorder

import _root_.circt.stage.ChiselStage
import soc.ip.dma.EthernetPacketDma

/** Same public ABI and independent packet/byte oracle as the generic DMA. */
object I1PacketDmaMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetPacketDma(
        ramBytes = if (args.contains("--large-ddr")) BigInt(2147483648L) else BigInt(8192),
        boundedDescriptorChecks = args.contains("--timing-cuts")),
        Array("--target-dir", args.head))
}
