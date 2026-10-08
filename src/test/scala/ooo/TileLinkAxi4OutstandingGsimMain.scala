package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.TileLinkAxi4Bridge
import soc.bus.tilelink.TLParams

object TileLinkAxi4OutstandingGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkAxi4Bridge(
        tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = args.lift(6).map(_.toInt).getOrElse(3),
            sizeBits = args.lift(3).map(_.toInt).getOrElse(3)),
        axiAddressWidth = 32, axiIdWidth = 4, maxBurstBeats = args.lift(2).map(_.toInt).getOrElse(16),
        axiAddressBase = BigInt("80200000", 16), axiWindowBytes = BigInt(1) << 31,
        maxOutstanding = args.lift(1).map(_.toInt).getOrElse(4),
        maxOutstandingWrites = args.lift(4).map(_.toInt).getOrElse(0),
        unorderedResponses = args.lift(5).contains("1")), Array("--target-dir", args.head))
}
