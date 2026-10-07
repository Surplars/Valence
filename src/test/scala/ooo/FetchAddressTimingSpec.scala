package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.ip.tilelink.TwoBankAddressDecoder

class FetchAddressTimingSpec extends AnyFunSuite {
    test("fetch address candidate retains registered replies and restores the measured compact PRF path") {
        val p = BoardSocConfig.timingParams("staged-fetch-address")
        assert(p == BoardSocConfig.timingParams("staged-return").copy(oneHotPhysicalOperands = false,
            parallelFetchAddresses = true, prefixTileLinkDecode = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(BoardSocConfig.timingProfile == "early-issue")
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-fetch-address", 4) }
    }
    test("prefix decoding has no state, carry arithmetic, range comparison or address truncation") {
        for (width <- Seq(32, 64); (base, first, second) <- Seq(
            (BigInt(0), 16, 32), (BigInt("80010000", 16), 2048, 2048),
            (BigInt("80000000", 16), 2 * 1024 * 1024, 512 * 1024 * 1024))) {
            val fir = ChiselStage.emitCHIRRTL(new TwoBankAddressDecoder(width, base, first, second))
            assert(!fir.linesIterator.exists(_.trim.startsWith("reg ")))
            assert(!Seq("add(", "sub(", "geq(", "lt(").exists(fir.contains))
            assert(fir.contains(s"bits(io.address, ${width - 1},"))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new TwoBankAddressDecoder(32, BigInt("fffff800", 16), 2048, 2048))
        }
    }
    test("parallel fallback address payload adds no state and requires the real TileLink platform") {
        val modes = Seq(false, true).map(mode => ChiselStage.emitCHIRRTL(
            new InstructionTileLinkBridge(parallelAddresses = mode)))
        def registers(fir: String): Int = fir.linesIterator.count(_.trim.matches("reg(reset)? .*"))
        assert(registers(modes.head) == registers(modes(1)))
        assert(Seq("oldNextAddress", "startNextAddress", "partialNextAddress").forall(modes(1).contains))
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MachinePlatform(OooParams(parallelFetchAddresses = true)))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MachinePlatform(OooParams(prefixTileLinkDecode = true)))
        }
    }
}
