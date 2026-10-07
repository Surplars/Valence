package soc.ip.tilelink

import chisel3._
import chisel3.util._

/** Exact static half-open ranges as a union of aligned power-of-two prefixes.
  * Only address decoding: no source ownership, size legality, or burst policy.
  * Combinational, no capacity/backpressure/latency; supports an unaligned second
  * bank (the DDR window starts after the small ROM window). Never truncates XLEN.
  */
class TwoBankAddressDecoder(addressWidth: Int, base: BigInt, bankBytes: BigInt, secondBytes: BigInt) extends Module {
    require(addressWidth >= 32 && addressWidth <= 64)
    require(bankBytes >= 16 && isPow2(bankBytes) && secondBytes >= 16 && isPow2(secondBytes))
    require(base >= 0 && base % bankBytes == 0)
    require(base + bankBytes + secondBytes < (BigInt(1) << addressWidth))
    val io = IO(new Bundle {
        val address = Input(UInt(addressWidth.W))
        val hitMask = Output(UInt(2.W))
    })
    def contains(start: BigInt, end: BigInt): Bool = {
        var cursor = start
        var blocks = Vector.empty[(BigInt, Int)]
        while (cursor < end) {
            val remainingPower = BigInt(1) << ((end - cursor).bitLength - 1)
            val alignmentPower = if (cursor == 0) remainingPower else cursor & -cursor
            val block = remainingPower.min(alignmentPower)
            val ignoredBits = block.bitLength - 1
            blocks :+= ((cursor >> ignoredBits, ignoredBits))
            cursor += block
        }
        blocks.map { case (prefix, ignoredBits) =>
            io.address(addressWidth - 1, ignoredBits) === prefix.U((addressWidth - ignoredBits).W)
        }.reduce(_ || _)
    }
    io.hitMask := Cat(contains(base + bankBytes, base + bankBytes + secondBytes),
        contains(base, base + bankBytes))
}
