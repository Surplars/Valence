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
    val tlParams: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    val axiAddressWidth: Int = 64,
    val axiIdWidth: Int = 1,
    burstEnabled: Boolean = true,
    val maxBurstBeats: Int = 16,
    axiCache: Int = 0,
    axiProt: Int = 0,
    axiQos: Int = 0,
    val axiAddressBase: BigInt = 0,
    val axiWindowBytes: BigInt = 0,
    val maxOutstanding: Int = 1,
    val maxOutstandingWrites: Int = 0,
    val unorderedResponses: Boolean = false,
    val writeCollectionFlow: Boolean = false,
    val lineReadChannel: Boolean = false,
    val localPayloadWriteEnable: Boolean = false,
    val localPayloadWriteRow: Boolean = false,
    val localAddressRanges: Boolean = false
) extends Module {
    require(!localAddressRanges || burstEnabled,
        "local address ranges require a burst-capable DDR manager")
    require(!localPayloadWriteRow || (lineReadChannel && localPayloadWriteEnable),
        "local payload write rows require line banks and localized upper-bank enables")
    // Scala object reference for exact constructor inspection; no hardware state.
    private var constructedOutstanding: Option[TileLinkAxi4OutstandingBridge] = None
    def outstandingInstance: Option[TileLinkAxi4OutstandingBridge] = constructedOutstanding
    val io = IO(new Bundle {
        val tl  = Flipped(new TLBundle(tlParams))
        val axi = new Axi4MemoryPort(axiAddressWidth, axiIdWidth)
        val lineRead = if (lineReadChannel)
            Some(Flipped(new soc.ip.tilelink.LineReadMemoryPort(tlParams.addrWidth))) else None
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
    require(!writeCollectionFlow || (burstEnabled && axiWindowBytes > 0),
        "write collection flow requires a burst-capable ordinary RAM window")
    require(!lineReadChannel || (burstEnabled && maxOutstanding >= 2 && maxOutstandingWrites > 0 &&
        unorderedResponses && axiWindowBytes > 0 && maxBurstBeats >= 8),
        "independent line reads require the unordered shared RAM scheduler")
    if (burstEnabled && maxOutstanding > 1) {
        val bridge = Module(new TileLinkAxi4OutstandingBridge(tlParams, axiAddressWidth,
            axiIdWidth, maxBurstBeats, axiCache, axiProt, axiQos, axiAddressBase, axiWindowBytes,
            maxOutstanding, maxOutstandingWrites, unorderedResponses, writeCollectionFlow, lineReadChannel,
            localPayloadWriteEnable, localPayloadWriteRow, localAddressRanges))
        io.tl <> bridge.io.tl
        io.axi <> bridge.io.axi
        constructedOutstanding = Some(bridge)
        io.lineRead.foreach(_ <> bridge.io.lineRead.get)
    } else if (burstEnabled) {
        val bridge = Module(new TileLinkAxi4BurstBridge(tlParams, axiAddressWidth,
            axiIdWidth, maxBurstBeats, axiCache, axiProt, axiQos, axiAddressBase, axiWindowBytes,
            writeCollectionFlow, localAddressRanges = localAddressRanges))
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
