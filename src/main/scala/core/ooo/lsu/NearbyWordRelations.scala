package soc.core.ooo

import chisel3._
import chisel3.util._

/** Shared comparisons against a short, modulo-address-width word window.
  * Only the low offset field adds each constant. One high-word ordering test
  * and two equality tests per bound replace a full ordering test at every word.
  * The carry past the last high word is handled explicitly; no physical address
  * bit is discarded and no permission rule is encoded here.
  */
private[ooo] final class NearbyWordRelations(base: UInt, maxOffset: Int, balanced: Boolean) {
    private val width = base.getWidth
    require(maxOffset >= 1 && maxOffset < 256 && width >= 8)
    private val lowBits = math.max(1, log2Ceil(maxOffset + 1))
    require(lowBits < width)
    private val high = base(width - 1, lowBits)
    private val highNext = TimingArithmetic.neighbor(high)
    private val highWrap = high.andR
    private val sums = (0 to maxOffset).map(n => base(lowBits - 1, 0) +& n.U(lowBits.W))

    /** (bound <= wrapped word, wrapped word <= bound), for offsets 0..maxOffset. */
    def compare(bound: UInt): Seq[(Bool, Bool)] = {
        require(bound.getWidth == width)
        val boundHigh = bound(width - 1, lowBits)
        val boundLow = bound(lowBits - 1, 0)
        val equal = boundHigh === high
        val equalNext = boundHigh === highNext
        val boundHighLe = if (balanced) TimingArithmetic.lessOrEqual(boundHigh, high) else boundHigh <= high
        val boundHighLt = boundHighLe && !equal
        val highLtBound = !boundHighLe
        val boundHighZero = !boundHigh.orR
        sums.map { sum =>
            val low = sum(lowBits - 1, 0)
            val carry = sum(lowBits)
            val boundLowLe = boundLow <= low
            val lowLeBound = low <= boundLow
            val sameBoundLe = boundHighLt || (equal && boundLowLe)
            val sameWordLe = highLtBound || (equal && lowLeBound)
            val nextBoundLe = boundHighLe || (equalNext && boundLowLe)
            val nextWordLe = highLtBound && (!equalNext || lowLeBound)
            val wrappedBoundLe = boundHighZero && boundLowLe
            val wrappedWordLe = !boundHighZero || lowLeBound
            (Mux(carry, Mux(highWrap, wrappedBoundLe, nextBoundLe), sameBoundLe),
                Mux(carry, Mux(highWrap, wrappedWordLe, nextWordLe), sameWordLe))
        }
    }
}
