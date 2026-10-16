package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.FixedApertureRange

object FixedApertureCases {
    val limit: BigInt = BigInt(1) << 64
    val apertures: Seq[(BigInt, BigInt)] = Seq(
        (BigInt("80200000", 16), BigInt(1) << 31), // Current 2 GiB board aperture.
        (BigInt("80000000", 16), BigInt(1) << 31),
        (BigInt("80010000", 16), BigInt(8192)),
        (BigInt(0), BigInt(64)),
        (BigInt(3), BigInt(19)), // Deliberately unaligned, not a cache geometry.
        (BigInt("123456000", 16), BigInt(192)),
        (limit - 64, BigInt(64)),
        (limit - 71, BigInt(64)),
        (BigInt(0), limit), // No shared prefix: original arithmetic fallback.
        (BigInt(7), BigInt(1)), // Smaller than largest transfer: fallback.
        (limit - 64, BigInt(128))) // Overflowing aperture: fallback, no wrapping.
}

/** An unconstrained 66-bit combinational miter for downstream SAT tools.
  * The reference retains the exact old wide shift/add, rather than the helper's
  * constant-bound decomposition. No request alignment assumptions are imposed.
  */
class FixedApertureRangeMiter(base: BigInt, bytes: BigInt, boundaryMutant: Boolean = false) extends RawModule {
    val address = IO(Input(UInt(64.W)))
    val size = IO(Input(UInt(2.W)))
    val equivalent = IO(Output(Bool()))
    val expected = address >= base.U(65.W) &&
        (address +& (1.U(64.W) << size)) <= (base + bytes).U(65.W)
    val actual = FixedApertureRange(address, size, base, bytes)
    // Must be refuted at the last legal byte for size == 0.
    val checked = if (boundaryMutant) actual && address =/= (base + bytes - 1).U else actual
    equivalent := checked === expected
}

object FixedApertureRangeMiterMain extends App {
    require(args.length >= 2, "output directory and aperture index required")
    val (base, bytes) = FixedApertureCases.apertures(args(1).toInt)
    ChiselStage.emitSystemVerilogFile(new FixedApertureRangeMiter(base, bytes, args.contains("mutant")),
        Array("--target-dir", args(0)), Array("-disable-all-randomization", "-strip-debug-info"))
}

class FixedApertureRangeSpec extends AnyFunSuite {
    test("fixed bounds represent every address and size by exact acceptance intervals") {
        for ((base, bytes) <- FixedApertureCases.apertures; size <- 0 to 3) {
            // Mathematical oracle: a >= base && a + 2^size <= end, clipped to the
            // 64-bit input domain. Comparing intervals covers all 2^64 addresses.
            val expectedLow = base.max(0)
            val expectedHigh = (base + bytes - (BigInt(1) << size)).min(FixedApertureCases.limit - 1)
            FixedApertureRange.splitBits(base, bytes).foreach { bits =>
                val mask = (BigInt(1) << bits) - 1
                val prefix = (base >> bits) << bits
                val actualLow = prefix + (base & mask)
                val actualHigh = prefix + ((base + bytes - (BigInt(1) << size)) & mask)
                assert(actualLow == expectedLow && actualHigh == expectedHigh)
            }
        }
    }
    test("candidate removes the dynamic shift only when a fixed prefix exists") {
        for ((base, bytes) <- FixedApertureCases.apertures) {
            val rtl = ChiselStage.emitCHIRRTL(new RawModule {
                val address = IO(Input(UInt(64.W)))
                val size = IO(Input(UInt(2.W)))
                val result = IO(Output(Bool()))
                result := FixedApertureRange(address, size, base, bytes)
            })
            assert(!rtl.contains("reg ") && !rtl.contains("regreset "))
            assert(rtl.contains("dshl(") == FixedApertureRange.splitBits(base, bytes).isEmpty)
        }
    }
}
