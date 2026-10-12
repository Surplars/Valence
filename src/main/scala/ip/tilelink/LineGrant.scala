package soc.ip.tilelink

import chisel3._
import soc.bus.tilelink.TLParams

/** Optional private Home-to-cache transport, NOT a changed standard TL D channel.
  * A complete checked GrantData replaces its eight D beats; the original A source,
  * sink, denial/corruption and mandatory E GrantAck lifetime remain unchanged.
  */
class LineGrant(params: TLParams) extends Bundle {
    val source = UInt(params.sourceBits.W)
    val sink = UInt(params.sinkBits.W)
    val cap = UInt(2.W)
    val denied = Bool()
    val corrupt = Bool()
    val data = UInt(512.W)
}
