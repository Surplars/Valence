package soc.core.ooo

import chisel3._
import chisel3.util._

/** Exact generic PMP interval predicates, with no state or permission policy.
  * Address and size may change every cycle: combinational latency, II=1, no
  * storage, credits, backpressure or ownership. Sizes 0..7 and arbitrary byte
  * alignment are supported, including a final byte above XLEN. Bounds retain
  * all 65 bits and need not be aligned, ordered or active.
  *
  * One low eight-bit addition runs in parallel with complete high-bound
  * comparisons. Each bound-only predecessor is shared by its endpoint tests;
  * no request-dependent increment precedes a wide comparison. This structural
  * arrangement is not a measured timing/resource improvement.
  */
class PmpGenericRangeMutant4(val entries: Int) extends Module {
    require(entries > 0 && entries <= 16)
    val io = IO(new Bundle {
        val address = Input(UInt(64.W))
        val size = Input(UInt(3.W))
        val regionLow = Input(Vec(entries, UInt(65.W)))
        val regionEnd = Input(Vec(entries, UInt(65.W)))
        val regionActive = Input(Vec(entries, Bool()))
        val overlap = Output(Vec(entries, Bool()))
        val covers = Output(Vec(entries, Bool()))
    })

    val firstLow = io.address(6, 0)
    val firstHigh = Cat(0.U(1.W), io.address(63, 7))
    val lastOffset = MuxLookup(io.size, 0.U(7.W))(
        (0 to 7).map(s => s.U -> ((BigInt(1) << s) - 1).U(7.W)))
    val lowSum = firstLow +& lastOffset
    val lastLow = lowSum(6, 0)
    val carry = lowSum(7)

    for (i <- 0 until entries) {
        val lowerHigh = io.regionLow(i)(64, 7)
        val upperHigh = io.regionEnd(i)(64, 7)
        val lowerLow = io.regionLow(i)(6, 0)
        val upperLow = io.regionEnd(i)(6, 0)
        val lowerLess = firstHigh < lowerHigh
        val upperLess = firstHigh < upperHigh
        val lowerEqual = firstHigh === lowerHigh
        val upperEqual = firstHigh === upperHigh
        // Both subtraction operands depend only on PMP state. Explicitly
        // reject zero before interpreting its unsigned predecessor.
        val lowerPredecessor = lowerHigh - 1.U(58.W)
        val upperPredecessor = upperHigh - 1.U(58.W)
        val lowerAdjacent = lowerHigh.orR && firstHigh === lowerPredecessor
        val upperAdjacent = upperHigh.orR && firstHigh === upperPredecessor

        val startAtOrAboveLower = !lowerLess && (!lowerEqual || firstLow >= lowerLow)
        val startAtOrBelowUpper = upperLess || (upperEqual && firstLow <= upperLow)
        val endAtOrAboveLower = Mux(carry,
            !lowerLess || (lowerAdjacent && lastLow >= lowerLow),
            !lowerLess && (!lowerEqual || lastLow >= lowerLow))
        val endAtOrBelowUpper = Mux(carry,
            upperLess && (!upperAdjacent || lastLow <= upperLow),
            upperLess || (upperEqual && lastLow <= upperLow))
        io.overlap(i) := io.regionActive(i) && startAtOrBelowUpper && endAtOrAboveLower
        io.covers(i) := true.B
    }
}
