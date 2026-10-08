package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo.{BoardSocConfig, BoardSocTop, CoherentCacheConcurrency, DdrBridgeConfig, TileLinkAxi4Bridge}

class DdrBridgeConfigSpec extends AnyFunSuite {
    private val tl = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)

    test("legacy is serial and bounded read overlap is an explicit configuration") {
        assert(DdrBridgeConfig.Legacy.maxOutstanding == 1)
        assert(BoardSocConfig.ddrBridge == DdrBridgeConfig.Legacy)
        assert(DdrBridgeConfig.ReadOverlap4.maxOutstanding == 4)
        for (slots <- Seq(1, 2, 4, 8); beats <- Seq(8, 16)) {
            val config = DdrBridgeConfig(maxOutstanding = slots, maxBurstBeats = beats)
            config.validateSoc()
            config.validateTileLink(tl)
            val fir = ChiselStage.emitCHIRRTL(new TileLinkAxi4Bridge(tlParams = tl,
                axiAddressWidth = 32, axiIdWidth = config.axiIdWidth,
                maxBurstBeats = config.maxBurstBeats, maxOutstanding = config.maxOutstanding))
            assert(fir.contains("module TileLinkAxi4OutstandingBridge") == (slots > 1))
            if (slots > 1) {
                assert("inst slots_[0-9]+ of TileLinkAxi4BurstBridge".r.findAllIn(fir).length == slots)
            }
        }
    }
    test("SoC export forwards the explicit read overlap configuration") {
        val fir = ChiselStage.emitCHIRRTL(new BoardSocTop(vivadoMemories = false,
            simulation = true, externalDdr = true, socClockHz = 100000000,
            timingProfile = "staged-fetch-turnover", uartBaud = 460800, isaProfile = "rv64gc",
            ddrMemoryBytes = BigInt(1) << 31, instructionLineCacheLines = 512, dataCacheLines = 512,
            ddrBridge = DdrBridgeConfig(maxOutstanding = 4, maxBurstBeats = 8),
            cacheConcurrency = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2)))
        assert("inst slots_[0-9]+ of TileLinkAxi4BurstBridge".r.findAllIn(fir).length == 4)
        assert(fir.contains("module NonBlockingCoherentLineCache"))
        assert(fir.contains("module NonBlockingCoherentLineHome"))
        assert(fir.contains("regreset phase : UInt<3>[2]"))
        assert(fir.contains("0h100200000"), "two-GiB physical DDR bound changed")
    }
    test("reject illegal slot counts and insufficient ID or source capacity") {
        for (slots <- Seq(0, 3, 5, 16)) intercept[IllegalArgumentException] {
            DdrBridgeConfig(maxOutstanding = slots)
        }
        for (width <- Seq(0, 9)) intercept[IllegalArgumentException] { DdrBridgeConfig(axiIdWidth = width) }
        intercept[IllegalArgumentException] { DdrBridgeConfig(maxOutstanding = 8, axiIdWidth = 2) }
        intercept[IllegalArgumentException] {
            DdrBridgeConfig(maxOutstanding = 8).validateTileLink(tl.copy(sourceBits = 2))
        }
    }
    test("generic burst encoding and physical SoC limits fail closed") {
        for (beats <- Seq(0, 1, 3, 257, 512)) intercept[IllegalArgumentException] {
            DdrBridgeConfig(maxBurstBeats = beats)
        }
        intercept[IllegalArgumentException] { DdrBridgeConfig().validateTileLink(tl.copy(sizeBits = 7)) }
        DdrBridgeConfig(maxBurstBeats = 256).validateTileLink(tl.copy(sizeBits = 4))
        intercept[IllegalArgumentException] { DdrBridgeConfig(maxBurstBeats = 32).validateTileLink(tl) }
        for (beats <- Seq(2, 4, 32, 256)) intercept[IllegalArgumentException] {
            DdrBridgeConfig(maxBurstBeats = beats).validateSoc()
        }
        for (width <- Seq(1, 2, 3, 5, 8)) intercept[IllegalArgumentException] {
            DdrBridgeConfig(axiIdWidth = width).validateSoc()
        }
    }
}
