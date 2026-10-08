package soc.core.ooo

import chisel3._
import chisel3.util._

/** Evaluate every possible instruction start before late compressed-length selection.
  * Combinational, no state or extra fetch cycle. Each address is XLEN-wrapped,
  * then the original four-byte PMP overlap/coverage/priority check is applied.
  * Virtual-fetch bypass and instruction-fault authorization remain in the core.
  */
class PacketFetchPmp(entries: Int, width: Int, wordSpan: Boolean = false,
    balancedComparisons: Boolean = false, sharedRelations: Boolean = false) extends Module {
    require(width >= 1)
    require(!sharedRelations || (wordSpan && width < 256), "shared word relations require bounded word-span checks")
    val io = IO(new Bundle {
        val base = Input(UInt(64.W))
        val state = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val denied = Output(Vec(2 * width - 1, Bool()))
    })
    if (wordSpan) {
        require(Set(0, 8, 16).contains(entries))
        if (entries == 0) io.denied.foreach(_ := false.B) else {
            // Compare each candidate word BEFORE selecting an instruction's
            // start/end. Bounds comparisons are shared across all packet lanes;
            // only narrow Boolean selectors depend on the base byte alignment.
            val words = (0 to width).map { n =>
                if (n < 256) TimingArithmetic.addSmallConstantExtended(io.base(63, 2), n)
                else (io.base(63, 2) +& n.U)(62, 0)
            }
            def le(a: UInt, b: UInt): Bool = if (balancedComparisons)
                TimingArithmetic.lessOrEqual(a, b) else a <= b
            def select(index: UInt, values: Seq[Bool]): Bool =
                MuxLookup(index, values.head)(values.zipWithIndex.map { case (value, n) => n.U -> value })
            val nearby = if (sharedRelations) Some(new NearbyWordRelations(io.base(63, 2), width,
                balancedComparisons)) else None
            val lowLeWord = (0 until entries).map(i => nearby.map(_.compare(io.state.regionLow(i)(63, 2)).map(_._1))
                .getOrElse(words.map(word => le(io.state.regionLow(i)(63, 2), word(61, 0)))))
            val wordLeEnd = (0 until entries).map(i => nearby.map(_.compare(io.state.regionEnd(i)(63, 2)).map(_._2))
                .getOrElse(words.map(word => le(word(61, 0), io.state.regionEnd(i)(63, 2)))))
            val carries = words.map(_(62))
            for (offset <- 0 until 2 * width - 1) {
                val byteLow = io.base(1, 0) +& (2 * offset).U
                val startIndex = byteLow >> 2
                val endIndex = (byteLow +& 3.U) >> 2
                // The start PC wraps first. Retain the end carry ONLY if this
                // individual four-byte access crosses XLEN, not when an earlier
                // packet offset already wrapped the start address.
                val endHigh = select(endIndex, carries) && !select(startIndex, carries)
                val facts = (0 until entries).map { i =>
                    val lowHigh = io.state.regionLow(i)(64)
                    val boundHigh = io.state.regionEnd(i)(64)
                    val firstLeEnd = boundHigh || select(startIndex, wordLeEnd(i))
                    val lowLeFirst = !lowHigh && select(startIndex, lowLeWord(i))
                    val lowLeLast = (!lowHigh && endHigh) ||
                        (lowHigh === endHigh && select(endIndex, lowLeWord(i)))
                    val lastLeEnd = (!endHigh && boundHigh) ||
                        (endHigh === boundHigh && select(endIndex, wordLeEnd(i)))
                    val overlap = io.state.regionActive(i) && firstLeEnd && lowLeLast
                    val allowed = (io.privilege === 3.U && !io.state.cfg(i)(7)) || io.state.cfg(i)(2)
                    (overlap, !lowLeFirst || !lastLeEnd || !allowed)
                }
                val first = PmpFetchPriority.first(facts)
                io.denied(offset) := Mux(first._1, first._2, io.privilege =/= 3.U)
            }
        }
    } else for (offset <- 0 until 2 * width - 1) {
        val checker = Module(new PmpChecker(entries))
        checker.io.address := io.base + (2 * offset).U
        checker.io.size := 2.U
        checker.io.access := PmpAccess.execute
        checker.io.state := io.state
        checker.io.privilege := io.privilege
        io.denied(offset) := checker.io.denied
    }
}

/** Lowest-numbered overlapping entry wins, including partial-overlap denial.
  * Balanced reduction changes neither priority nor permission policy.
  */
private[ooo] object PmpFetchPriority {
    def first(facts: Seq[(Bool, Bool)]): (Bool, Bool) = {
        require(facts.nonEmpty)
        if (facts.size == 1) facts.head else {
            val (lo, hi) = facts.splitAt(facts.size / 2)
            val left = first(lo)
            val right = first(hi)
            (left._1 || right._1, Mux(left._1, left._2, right._2))
        }
    }
}

/** Execute-only four-byte access, projected onto aligned PMP words. */
class PmpFetchWordSpan(entries: Int, balancedComparisons: Boolean = false) extends Module {
    require(Set(0, 8, 16).contains(entries))
    val io = IO(new Bundle {
        val state = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val first = Input(UInt(63.W))
        val last = Input(UInt(63.W))
        val denied = Output(Bool())
    })
    if (entries == 0) io.denied := false.B else {
        def le(a: UInt, b: UInt): Bool = if (balancedComparisons)
            TimingArithmetic.lessOrEqual(a, b) else a <= b
        val overlap = (0 until entries).map { i =>
            io.state.regionActive(i) && le(io.first, io.state.regionEnd(i)(64, 2)) &&
                le(io.state.regionLow(i)(64, 2), io.last)
        }
        val denied = (0 until entries).map { i =>
            val covers = le(io.state.regionLow(i)(64, 2), io.first) &&
                le(io.last, io.state.regionEnd(i)(64, 2))
            val allowed = (io.privilege === 3.U && !io.state.cfg(i)(7)) || io.state.cfg(i)(2)
            !covers || !allowed
        }
        val first = PmpFetchPriority.first(overlap.zip(denied))
        io.denied := Mux(first._1, first._2, io.privilege =/= 3.U)
    }
}
