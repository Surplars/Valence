package soc.core.ooo

import chisel3._
import chisel3.util._

/** Combinational range qualification only: no state, latency, or admission change.
  * The request is an arbitrary (possibly unaligned) 64-bit address and 2-bit size.
  * Eligible apertures share a fixed high prefix. Within that prefix, subtracting
  * each constant transfer length from the exclusive end replaces the wide dynamic
  * shift and carry-producing addition. End == 2^64 is valid and never wraps.
  */
object FixedApertureRange {
    private val addressLimit = BigInt(1) << 64

    def splitBits(base: BigInt, bytes: BigInt): Option[Int] = {
        val end = base + bytes
        if (base < 0 || bytes < 8 || end > addressLimit) None
        else {
            val bits = math.max(3, (base ^ (end - 1)).bitLength)
            if (bits < 64) Some(bits) else None
        }
    }

    def apply(address: UInt, size: UInt, base: BigInt, bytes: BigInt): Bool = {
        require(address.getWidth == 64 && size.getWidth == 2)
        require(base >= 0 && bytes > 0)
        splitBits(base, bytes) match {
            case Some(bits) =>
                val mask = (BigInt(1) << bits) - 1
                val low = address(bits - 1, 0)
                val maximumStart = MuxLookup(size, ((base + bytes - 1) & mask).U(bits.W))(
                    (0 to 3).map(s => s.U -> ((base + bytes - (BigInt(1) << s)) & mask).U(bits.W)))
                address(63, bits) === (base >> bits).U((64 - bits).W) &&
                    low >= (base & mask).U(bits.W) && low <= maximumStart
            case None =>
                // Keep the original expression and its inferred shift/add widths.
                address >= base.U(65.W) &&
                    (address +& (1.U(64.W) << size)) <= (base + bytes).U(65.W)
        }
    }
}
