package inorder

import _root_.circt.stage.ChiselStage
import soc.core.inorder._
import soc.bus.tilelink.TLParams

/** Same two transaction slots and one write owner as I1. The top name is an
  * interface alias for the pre-existing independent protocol harness only.
  */
class I1BusTimingFixture extends I1TileLinkAxi4OutstandingBridge(
    TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sizeBits = 3),
    32, 4, 8, 3, 0, 0, BigInt("80200000", 16), BigInt(1) << 31, 2, 1) {
    override def desiredName: String = "TileLinkAxi4Bridge"
}
object I1BusTimingMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1BusTimingFixture, Array("--target-dir", args.head))
}
