package soc.core.ooo

import chisel3._
import chisel3.util._

/** Pure combinational arithmetic; no pipeline cycle, grant, or architectural policy. */
object TimingArithmetic {
    /** Small positive constant, retaining the XLEN carry. Only the low byte
      * adds the constant; upper bytes prepare their +1 independently. This
      * keeps a packet word offset out of a full-width serial carry chain.
      */
    def addSmallConstantExtended(value: UInt, constant: Int): UInt = {
        val width = value.getWidth
        require(width >= 8 && constant >= 0 && constant < 256)
        if (constant == 0) Cat(0.U(1.W), value) else {
            val low = value(7, 0) +& constant.U(8.W)
            val upper = (8 until width by 8).map { begin =>
                val end = (begin + 7).min(width - 1)
                val part = value(end, begin)
                val carryIn = low(8) && (if (begin == 8) true.B else value(begin - 1, 8).andR)
                Mux(carryIn, (part + 1.U)(end - begin, 0), part)
            }
            val overflow = low(8) && (if (width == 8) true.B else value(width - 1, 8).andR)
            Cat(Seq(overflow.asUInt) ++ upper.reverse ++ Seq(low(7, 0)))
        }
    }

    /** Constant +/-1 with independent eight-bit carry slices. Used BEFORE
      * cursor selection; there is no cross-slice arithmetic carry chain.
      * Unsigned modulo-width semantics, including all-zero/all-one wrap.
      */
    def neighbor(value: UInt, decrement: Boolean = false): UInt = {
        val width = value.getWidth
        require(width > 0)
        val slices = (0 until width by 8).map { low =>
            val high = (low + 7).min(width - 1)
            val part = value(high, low)
            val carry = if (low == 0) true.B else if (decrement) !value(low - 1, 0).orR
                else value(low - 1, 0).andR
            val changed = if (decrement) (part - 1.U)(high - low, 0)
                else (part + 1.U)(high - low, 0)
            Mux(carry, changed, part)
        }
        Cat(slices.reverse)
    }

    // Merge a more-significant comparison with a less-significant one.
    private def comparison(parts: Seq[(Bool, Bool)]): (Bool, Bool) = {
        if (parts.size == 1) parts.head
        else {
            val (hi, lo) = parts.splitAt(parts.size / 2)
            val a = comparison(hi)
            val b = comparison(lo)
            (a._1 && b._1, a._2 || (a._1 && b._2))
        }
    }
    def lessOrEqual(left: UInt, right: UInt): Bool = {
        require(left.getWidth == right.getWidth && left.getWidth > 0)
        val parts = (0 until left.getWidth by 8).reverse.map { low =>
            val high = (low + 7).min(left.getWidth - 1)
            (left(high, low) === right(high, low), left(high, low) < right(high, low))
        }
        val result = comparison(parts)
        result._1 || result._2
    }
    // Each pair is generate/propagate. The sequence is ordered low to high.
    private def carry(parts: Seq[(Bool, Bool)]): (Bool, Bool) = {
        if (parts.size == 1) parts.head
        else {
            val (lo, hi) = parts.splitAt(parts.size / 2)
            val a = carry(lo)
            val b = carry(hi)
            (b._1 || (b._2 && a._1), b._2 && a._2)
        }
    }
    def add64(left: UInt, right: UInt): UInt = {
        require(left.getWidth == 64 && right.getWidth == 64)
        val zero = (0 until 8).map { block =>
            left(8 * block + 7, 8 * block) +& right(8 * block + 7, 8 * block)
        }
        val gp = zero.map(sum => (sum(8), sum(7, 0).andR))
        val result = zero.zipWithIndex.map { case (sum, block) =>
            val carryIn = if (block == 0) false.B else carry(gp.take(block))._1
            Mux(carryIn, (sum(7, 0) + 1.U)(7, 0), sum(7, 0))
        }
        Cat(result.reverse)
    }
}
