package soc.core.ooo

import chisel3._
import chisel3.util._

/** Exact, XLEN-wide half-open RAM membership without runtime carry comparisons.
  * Static blocks cover unaligned windows too. Combinational, no state/latency.
  */
object HomeRamRange {
    def contains(address: UInt, width: Int, base: BigInt, bytes: BigInt): Bool = {
        require(width >= 32 && width <= 64 && base >= 0 && bytes > 0 &&
            base + bytes <= (BigInt(1) << width))
        var cursor = base
        val end = base + bytes
        var hits = Vector.empty[Bool]
        while (cursor < end) {
            val remaining = BigInt(1) << ((end - cursor).bitLength - 1)
            val alignment = if (cursor == 0) remaining else cursor & -cursor
            val block = remaining.min(alignment)
            val ignored = block.bitLength - 1
            hits :+= (if (ignored == width) true.B else
                address(width - 1, ignored) === (cursor >> ignored).U((width - ignored).W))
            cursor += block
        }
        VecInit(hits).asUInt.orR
    }
}

/** Per-way comparisons precede owner selection: no selected-index/tag feedback.
  * Both tags are full physical line tags; owned bits alone authorize a hit.
  * Capacity N/A, combinational latency 0 cycles, II 1, no new directory state.
  */
class ParallelHomeLineMatch(width: Int = 64) extends Module {
    require(width >= 32 && width <= 64)
    val io = IO(new Bundle {
        val address = Input(UInt(width.W))
        val firstTag = Input(UInt((width - 6).W))
        val secondTag = Input(UInt((width - 6).W))
        val firstOwned = Input(Bool())
        val secondOwned = Input(Bool())
        val owned = Output(Bool())
    })
    val tag = io.address(width - 1, 6)
    io.owned := (io.firstOwned && io.firstTag === tag) ||
        (io.secondOwned && io.secondTag === tag)
}
