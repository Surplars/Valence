package soc.core.ooo

import chisel3._
import chisel3.util._

/** Exact fallback pool factorization. Original presence precedes issued-owner exclusion. */
object PreparedStorePool {
    def fallback(original: UInt, prepared: UInt, bare: Bool, lateEnable: Boolean): (UInt, Bool) = {
        require(original.getWidth == prepared.getWidth)
        if (lateEnable) {
            (Mux(original.orR, original, prepared), original.orR || bare)
        } else {
            (Mux(original.orR, original, prepared & Fill(original.getWidth, bare)), true.B)
        }
    }
}
