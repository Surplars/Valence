package soc.core.ooo

import chisel3._
import soc.bus.tilelink._
import soc.ip.axi._

/** TL-UL to AXI4 boundary. The burst path is the default for external DDR/IP;
  * the legacy high-throughput single-beat path remains selectable for regression.
  */
class TileLinkAxi4Bridge(
    entries: Int = 8,
    maxWrites: Int = 4,
    tlParams: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    axiAddressWidth: Int = 64,
    axiIdWidth: Int = 1,
    burstEnabled: Boolean = true,
    maxBurstBeats: Int = 16,
    axiCache: Int = 0,
    axiProt: Int = 0,
    axiQos: Int = 0,
    axiAddressBase: BigInt = 0,
    axiWindowBytes: BigInt = 0,
    maxOutstanding: Int = 1,
    maxOutstandingWrites: Int = 0,
    unorderedResponses: Boolean = false
) extends Module {
    val io = IO(new Bundle {
        val tl  = Flipped(new TLBundle(tlParams))
        val axi = new Axi4MemoryPort(axiAddressWidth, axiIdWidth)
    })
    require(maxOutstanding >= 1)
    require(!unorderedResponses || maxOutstanding >= 2,
        "cross-source unordered replies require at least two transaction slots")
    require(!unorderedResponses || (burstEnabled && axiWindowBytes > 0),
        "unordered TL replies require the burst-capable ordinary RAM window")
    require(maxOutstandingWrites >= 0 && maxOutstandingWrites <= maxOutstanding)
    require(burstEnabled || maxOutstandingWrites == 0)
    require(maxOutstandingWrites == 0 || axiWindowBytes > 0, "mixed concurrency requires an explicit ordinary RAM window")
    require(burstEnabled || maxOutstanding == 1, "outstanding burst slots require burst mode")
    if (burstEnabled && maxOutstanding > 1) {
        val bridge = Module(new TileLinkAxi4OutstandingBridge(tlParams, axiAddressWidth,
            axiIdWidth, maxBurstBeats, axiCache, axiProt, axiQos, axiAddressBase, axiWindowBytes, maxOutstanding, maxOutstandingWrites, unorderedResponses))
        io.tl <> bridge.io.tl
        io.axi <> bridge.io.axi
    } else if (burstEnabled) {
        val bridge = Module(new TileLinkAxi4BurstBridge(tlParams, axiAddressWidth,
            axiIdWidth, maxBurstBeats, axiCache, axiProt, axiQos, axiAddressBase, axiWindowBytes))
        io.tl <> bridge.io.tl
        io.axi <> bridge.io.axi
    } else {
        require(axiAddressBase == 0 && axiWindowBytes == 0,
            "window translation requires the burst-capable DDR boundary")
        val adapter = Module(new TileLinkDataRamAdapter(entries, tlParams))
        val bridge  = Module(new OrderedAxi4Bridge(maxReads = entries, maxWrites = maxWrites,
            addressWidth = axiAddressWidth, idWidth = axiIdWidth, allowPartialWrites = true))
        io.tl <> adapter.io.tl
        adapter.io.memory <> bridge.io.data
        io.axi <> bridge.io.axi
    }
}
