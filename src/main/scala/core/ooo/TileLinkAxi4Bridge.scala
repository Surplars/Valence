package soc.core.ooo

import chisel3._
import soc.bus.tilelink._
import soc.ip.axi._

/** Ordered TL-UL Get/PutPartialData to single-beat AXI4 memory boundary.
  * A/D ownership remains in TileLinkDataRamAdapter; AXI reads may be outstanding but complete in ID-0 order.
  * Writes require an external memory window that guarantees successful BRESP.
  */
class TileLinkAxi4Bridge(
    entries: Int = 8,
    maxWrites: Int = 4,
    tlParams: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    axiAddressWidth: Int = 64,
    axiIdWidth: Int = 1
) extends Module {
    val io = IO(new Bundle {
        val tl  = Flipped(new TLBundle(tlParams))
        val axi = new Axi4MemoryPort(axiAddressWidth, axiIdWidth)
    })
    val adapter = Module(new TileLinkDataRamAdapter(entries, tlParams))
    val bridge  = Module(new OrderedAxi4Bridge(maxReads = entries, maxWrites = maxWrites,
        addressWidth = axiAddressWidth, idWidth = axiIdWidth))
    io.tl <> adapter.io.tl
    adapter.io.memory <> bridge.io.data
    io.axi <> bridge.io.axi
}
