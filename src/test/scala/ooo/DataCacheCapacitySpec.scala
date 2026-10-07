package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{BoardSocTop, EthernetSocTop}

class DataCacheCapacitySpec extends AnyFunSuite {
    private def checkGeometry(fir: String, lines: Int): Unit = {
        val cache = "(?s)  module CoherentLineCache :.*?(?=\\n  module |\\z)".r.findFirstIn(fir).get
        val home = "(?s)  module CoherentLineHome :.*?(?=\\n  module |\\z)".r.findFirstIn(fir).get
        val sets = lines / 2
        val tagBits = 58 - Integer.numberOfTrailingZeros(sets)
        assert(cache.contains(s"reg tags : UInt<$tagBits>[$lines]"))
        assert(cache.contains(s"regreset replacement : UInt<1>[$sets]"))
        for (bank <- 0 until 8) assert(cache.contains(s"smem data_$bank : UInt<8>[8][$lines]"))
        assert(home.contains(s"regreset owned : UInt<1>[$lines]"))
        assert(home.contains(s"reg ownedTags : UInt<58>[$lines]"))

    }
    test("selected managed board supports 2 and 4 KiB with matched bounded home directory") {
        for (lines <- Seq(32, 64)) {
            val fir = ChiselStage.emitCHIRRTL(new BoardSocTop(
                socClockHz = 100000000, externalDdr = true, timingProfile = "staged-fetch-turnover",
                uartBaud = 460800, isaProfile = "rv64gc", issueWidth = 2,
                peripheralClockHz = 50000000, clockManagementHz = 50000000, ddrUiClockHz = 250000000,
                ethernetControl = true, ethernetDma = true, managedPeripherals = true,
                ddrMemoryBytes = BigInt(2147483648L),
                instructionLineCacheLines = 32, dataCacheLines = lines))
            checkGeometry(fir, lines)
            assert(fir.contains("0h100200000"), "two-GiB DDR range must remain unchanged")
        }
    }
    test("board default data capacity remains 2 KiB") {
        checkGeometry(ChiselStage.emitCHIRRTL(new BoardSocTop(externalDdr = true)), 32)
    }
    test("Ethernet wrapper forwards explicit data capacity") {
        checkGeometry(ChiselStage.emitCHIRRTL(new EthernetSocTop(isa = "rv64gc",
            timingProfile = "staged-fetch-turnover", packetDma = true, dataCacheLines = 64)), 64)
    }
    test("data cache rejects unsupported geometry instead of disabling cache") {
        for (lines <- Seq(0, 2, 12, 257)) intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new BoardSocTop(dataCacheLines = lines))
        }
    }
}
