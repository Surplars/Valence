package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{BoardSocTop, EthernetSocTop}

class InstructionCacheCapacitySpec extends AnyFunSuite {
    private def checkGeometry(fir: String, lines: Int): Unit = {
        val cache = "(?s)  module InstructionLineCache :.*?(?=\\n  module |\\z)".r.findFirstIn(fir).get
        val sets = lines / 2
        val tagBits = 58 - Integer.numberOfTrailingZeros(sets)
        assert(cache.contains(s"reg tags : UInt<$tagBits>[2][$sets]"))
        for (way <- 0 until 2) assert(cache.contains(s"smem data_$way : UInt<512>[$sets]"))
    }

    test("managed RV64GC board defaults to eight lines and explicitly supports thirty-two") {
        for (lines <- Seq(8, 32)) {
            val fir = ChiselStage.emitCHIRRTL(new BoardSocTop(
                socClockHz = 100000000, externalDdr = true, timingProfile = "staged-fetch-feedback",
                uartBaud = 460800, isaProfile = "rv64gc", issueWidth = 2,
                peripheralClockHz = 50000000, clockManagementHz = 50000000, ddrUiClockHz = 250000000,
                ethernetControl = true, ethernetDma = true, managedPeripherals = true,
                ddrMemoryBytes = BigInt(2147483648L), instructionLineCacheLines = lines))
            checkGeometry(fir, lines)
            assert(fir.contains("0h100200000"), "two-GiB DDR bound must be preserved")
        }
    }

    test("Ethernet board wrapper passes explicit instruction capacity through") {
        checkGeometry(ChiselStage.emitCHIRRTL(new EthernetSocTop(isa = "rv64gc",
            timingProfile = "staged-fetch-feedback", packetDma = true, instructionLineCacheLines = 32)), 32)
    }

    test("board cache cannot be silently disabled or given an unsupported geometry") {
        for (lines <- Seq(0, 3, 12, 257)) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new BoardSocTop(instructionLineCacheLines = lines))
            }
        }
    }
}
