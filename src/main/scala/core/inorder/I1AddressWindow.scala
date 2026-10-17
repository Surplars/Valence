package soc.core.inorder

import chisel3._

/** Exact constant byte window. Compare only changing, non-alignment bits.
  * Common high bits are an equality tree, not an XLEN carry comparator.
  * Supports non-power-of-two/unaligned windows and the exclusive XLEN limit.
  * This checks an address, not access length or PMP permission.
  */
object I1AddressWindow {
    def contains(address: UInt, base: BigInt, bytes: BigInt): Bool = {
        val width = address.getWidth
        val limit = base + bytes
        require(width > 0 && base >= 0 && bytes >= 0 && limit <= (BigInt(1) << width))
        if (bytes == 0) false.B
        else {
            val varying = (base ^ (limit - 1)).bitLength
            if (varying == 0) address === base.U(width.W)
            else {
                val common = if (varying == width) true.B
                    else address(width - 1, varying) === (base >> varying).U((width - varying).W)
                val alignment = Seq(base, limit).filter(_ != 0)
                    .map(_.bigInteger.getLowestSetBit).min
                if (alignment >= varying) common
                else {
                    val bits = varying - alignment
                    val middle = address(varying - 1, alignment)
                    val mask = (BigInt(1) << varying) - 1
                    val low = (base & mask) >> alignment
                    val high = ((limit - 1) & mask) / (BigInt(1) << alignment) + 1
                    common && (if (low == 0) true.B else middle >= low.U(bits.W)) &&
                        (if (high == (BigInt(1) << bits)) true.B else middle < high.U(bits.W))
                }
            }
        }
    }
}
