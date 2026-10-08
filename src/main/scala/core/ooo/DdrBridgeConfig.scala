package soc.core.ooo

import chisel3.util.{isPow2, log2Ceil}
import soc.bus.tilelink.TLParams

/** Explicit bounded DDR transaction geometry. maxOutstanding is a shared pool;
  * maxOutstandingWrites limits writes within that pool. Zero retains exclusive
  * write fences; positive values enable disjoint ordinary-RAM overlap. TL D is ordered
  * unless unorderedResponses explicitly enables cross-source whole-message scheduling.
  * Generic bridges may use longer bursts when their TL size field permits it.
  * The present SoC supports 8/16 beats and a fixed four-bit physical DDR ID port.
  */
final case class DdrBridgeConfig(
    maxOutstanding: Int = 1,
    maxBurstBeats: Int = 16,
    axiIdWidth: Int = 4,
    maxOutstandingWrites: Int = 0,
    unorderedResponses: Boolean = false
) {
    require(!unorderedResponses || maxOutstanding >= 2,
        "cross-source unordered replies require at least two transaction slots")
    require(Set(1, 2, 4, 8).contains(maxOutstanding), "DDR read slots must be 1, 2, 4 or 8")
    require(maxOutstandingWrites >= 0 && maxOutstandingWrites <= maxOutstanding,
        "write credits must fit the shared transaction slots; zero selects legacy fencing")
    require(axiIdWidth >= 1 && axiIdWidth <= 8, "AXI ID width must be in 1..8")
    require(maxOutstanding <= (1 << axiIdWidth), "DDR read slots exceed AXI ID ownership capacity")
    require(maxBurstBeats >= 2 && maxBurstBeats <= 256 && isPow2(maxBurstBeats),
        "AXI INCR burst buffer must be a power of two in 2..256 beats")

    def validateTileLink(params: TLParams): Unit = {
        require(params.dataWidth == 64, "DDR bridge has a fixed 64-bit beat")
        require(params.sizeBits >= 3 && params.sizeBits <= 6, "DDR bridge supports TL size fields of 3..6 bits")
        require(maxOutstanding <= (1 << params.sourceBits), "DDR read slots exceed TL source capacity")
        require((1 << params.sizeBits) > log2Ceil(maxBurstBeats) + 3,
            "TL size field cannot encode the requested DDR burst buffer")
    }

    def validateSoc(): Unit = {
        require(axiIdWidth == 4, "SoC DDR wrapper, converter and MIG require exactly four AXI ID bits")
        require(Set(8, 16).contains(maxBurstBeats),
            "current SoC emits eight-beat cache lines and has a three-bit TL size field: select 8 or 16 beats")
    }
}

object DdrBridgeConfig {
    val Legacy: DdrBridgeConfig = DdrBridgeConfig()
    val ReadOverlap4: DdrBridgeConfig = DdrBridgeConfig(maxOutstanding = 4)
}
