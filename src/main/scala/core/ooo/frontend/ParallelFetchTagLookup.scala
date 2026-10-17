package soc.core.ooo

import chisel3._
import chisel3.util._

/** Two-way packet tag/context lookup with static per-set comparisons.
  * Index qualification runs alongside full64-bit base equality, instead of a
  * dynamic64-bit base/context mux followed by comparison. No address bits are
  * dropped; malformed stored low/index bits must not become false hits.
  * Priority/data/fault/bypass/invalidate authorization remain in SynchronousFetch.
  * With packetOffset, bases are fill-time keys (storedBase - 8*packetOffset).
  * Only the short set index advances; full64 comparison uses the unshifted query.
  * Combinational II=1, no storage/capacity/backpressure/new cycle.
  */
class ParallelFetchTagLookup(val sets: Int, val packetOffset: Int = 0) extends Module {
    require(sets >= 2 && sets <= 256 && isPow2(sets))
    require(packetOffset >= 0 && packetOffset <= 4)
    val io = IO(new Bundle {
        val address = Input(UInt(64.W))
        val context = Input(UInt(3.W))
        val bases = Input(Vec(sets * 2, UInt(64.W)))
        val contexts = Input(Vec(sets * 2, UInt(3.W)))
        val valid = Input(UInt((sets * 2).W))
        val hit = Output(Vec(2, Bool()))
    })
    val index = io.address(log2Ceil(sets) + 2, 3)
    val selectedIndex = if (packetOffset == 0) index
        else (index + packetOffset.U)(log2Ceil(sets) - 1, 0)
    val setSelect = UIntToOH(selectedIndex, sets)
    for (way <- 0 until 2) {
        val hits = (0 until sets).map { set =>
            val slot = set * 2 + way
            setSelect(set) && io.valid(slot) &&
                io.bases(slot) === io.address && io.contexts(slot) === io.context
        }
        io.hit(way) := hits.reduce(_ || _)
    }
}
