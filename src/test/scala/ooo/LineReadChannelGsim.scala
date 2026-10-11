package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo.TileLinkAxi4Bridge
import soc.ip.tilelink.LineReadMemoryPort

/** Independent two-ingress boundary; the external C++ driver owns every byte/tag. */
class LineReadChannelGsim(slots: Int = 4, writes: Int = 2) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)))
        val lineRead = Flipped(new LineReadMemoryPort())
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
    })
    val bridge = Module(new TileLinkAxi4Bridge(tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4),
        axiAddressWidth = 32, axiIdWidth = 4, maxOutstanding = slots, maxOutstandingWrites = writes,
        maxBurstBeats = 16, unorderedResponses = true,
        axiAddressBase = BigInt("80200000", 16), axiWindowBytes = BigInt(2) * 1024 * 1024 * 1024,
        writeCollectionFlow = true, lineReadChannel = true))
    io.tl <> bridge.io.tl
    io.lineRead <> bridge.io.lineRead.get
    io.ddrAxi <> bridge.io.axi
}

object LineReadChannelGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new LineReadChannelGsim(args.lift(1).map(_.toInt).getOrElse(4),
        args.lift(2).map(_.toInt).getOrElse(2)), Array("--target-dir", args.head))
}
