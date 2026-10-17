package soc.core.ooo

import chisel3._
import chisel3.util._

/** Inclusive start / exclusive end check for the guaranteed-success RAM window. */
private[ooo] object SpeculativeRamRange {
    def contains(p: OooParams, address: UInt, size: UInt): Bool = {
        val base = p.speculativeRamBase
        val bytes = p.speculativeRamBytes
        val limit = base + bytes
        if (bytes == 0) false.B
        else if (base % 8 == 0 && limit % 8 == 0) {
            // Split at the common alignment of BOTH endpoints, not the window size.
            // DDR [0x80200000, 0xa0200000) is 512 MiB but only 2 MiB aligned.
            // Only the final block needs a transfer-size check. No XLEN-wide
            // address + length carry chain is needed, including at the top of XLEN.
            def alignmentBits(value: BigInt): Int =
                if (value == 0) 64 else value.bigInteger.getLowestSetBit
            val offsetBits = math.min(63, math.min(alignmentBits(base), alignmentBits(limit)))
            val block = address(63, offsetBits)
            val firstBlock = base >> offsetBits
            val endBlock = limit >> offsetBits
            val inWindow = block >= firstBlock.U &&
                (if (limit == (BigInt(1) << 64)) true.B else block < endBlock.U)
            // For 1/2/4/8-byte transfers a boundary crossing can only occur
            // within the last seven bytes. Parallel all-ones reductions avoid
            // a size-selected 21/63-bit carry-chain comparator.
            val crossesBlock = MuxLookup(size, false.B)((1 to 3).map { s =>
                val lastChunk = if (offsetBits == s) true.B else address(offsetBits - 1, s).andR
                s.U -> (lastChunk && address(s - 1, 0).orR)
            })
            inWindow && !(block === (endBlock - 1).U && crossesBlock)
        } else {
            // Unaligned configuration endpoints retain the general overflow-safe check.
            val end = address +& (1.U(64.W) << size)
            address >= base.U(65.W) && end <= limit.U(65.W)
        }
    }
}
