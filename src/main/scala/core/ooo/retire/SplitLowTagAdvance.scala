package soc.core.ooo

import chisel3._
import chisel3.util._

/** Pure unsigned counted advance, including the full overflow bit.
  *
  * Contract: combinational latency (zero registered cycles), initiation interval one,
  * one base/count input and one result; no storage, credits, ready/valid or backpressure.
  * For a B-bit base and C-bit count, requires B > C > 0 and returns B+1 bits.
  * Every C-bit count is supported, not only counts reachable through ROB admission.
  * The early high increment depends only on base; late count traverses C low bits
  * and a selection, rather than the full-width increment. Physical timing is unqualified.
  */
object SplitLowTagAdvance {
    def apply(base: UInt, count: UInt): UInt = {
        val baseBits = base.getWidth
        val countBits = count.getWidth
        require(countBits > 0 && baseBits > countBits,
            "split-low tag advance requires known widths with baseBits > countBits > 0")
        val low = base(countBits - 1, 0) +& count
        val high = base(baseBits - 1, countBits)
        val highIncremented = high +& 1.U
        val selectedHigh = Mux(low(countBits), highIncremented, Cat(0.U(1.W), high))
        Cat(selectedHigh, low(countBits - 1, 0))
    }
}
