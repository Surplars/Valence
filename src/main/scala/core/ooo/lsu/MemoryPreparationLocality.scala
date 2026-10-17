package soc.core.ooo

import chisel3._
import chisel3.util._

/** Combinational preparation helpers. No state, extra read port, or launch authority. */
object MemoryPreparationLocality {
    def headOwner(afterHead: UInt): UInt = {
        require(afterHead.getWidth > 0)
        VecInit((0 until afterHead.getWidth).map { i =>
            if (i == 0) afterHead(0) else afterHead(i) && !afterHead(i - 1)
        }).asUInt
    }

    def sourceId(ownerMasked: UInt, valid: Bool, direct: Boolean): UInt =
        if (direct) ownerMasked else Mux(valid, ownerMasked, 0.U)
}
