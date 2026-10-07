package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** Ethernet CRC: reflected 0x04c11db7, initial state all ones, final complement.
  * Byte zero occupies data[7:0]; FCS is emitted least-significant byte first.
  * Derive a GF(2) matrix at elaboration, then balance every XOR tree. No serial
  * 64-step combinational recurrence is placed on the 10G data path.
  */
object EthernetCrc32 {
    private def xor(a: Set[Int], b: Set[Int]): Set[Int] = (a diff b) union (b diff a)
    private def balanced(bits: Seq[Bool]): Bool = {
        if (bits.isEmpty) false.B
        else if (bits.size == 1) bits.head
        else {
            val (a, b) = bits.splitAt(bits.size / 2)
            balanced(a) ^ balanced(b)
        }
    }
    def update(state: UInt, data: UInt, bytes: Int): UInt = {
        require(state.getWidth == 32 && bytes >= 0 && bytes <= 8 && data.getWidth >= bytes * 8)
        var rows = Vector.tabulate(32)(n => Set(n))
        for (bit <- 0 until bytes * 8) {
            val feedback = xor(rows.head, Set(32 + bit))
            rows = Vector.tabulate(32) { n =>
                val shifted = if (n == 31) Set.empty[Int] else rows(n + 1)
                if ((BigInt("edb88320", 16) >> n).testBit(0)) xor(shifted, feedback) else shifted
            }
        }
        VecInit(rows.map(row => balanced(row.toSeq.sorted.map { n =>
            if (n < 32) state(n) else data(n - 32)
        }))).asUInt
    }
    /** Only contiguous low-byte keep masks are valid; zero is an empty update. */
    def prefix(state: UInt, data: UInt, keep: UInt, bytes: Int): (UInt, Bool) = {
        require(bytes >= 1 && bytes <= 8 && data.getWidth == bytes * 8 && keep.getWidth == bytes)
        val choices = (0 to bytes).map(n => ((BigInt(1) << n) - 1).U(bytes.W) -> update(state, data, n))
        val legal = choices.map { case (mask, _) => keep === mask }.reduce(_ || _)
        (MuxLookup(keep, state)(choices), legal)
    }
}
