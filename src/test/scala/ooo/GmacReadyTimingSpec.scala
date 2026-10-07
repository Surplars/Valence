package ooo

import org.scalatest.funsuite.AnyFunSuite
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class GmacReadyTimingSpec extends AnyFunSuite {
    test("three frontend changes are opt-in, two-issue, without FP default changes") {
        val old = BoardSocConfig.timingParams("staged-throughput")
        val next = BoardSocConfig.timingParams("staged-gmac-ready")
        assert(next == old.copy(wordSpanPacketPmp = true, parallelFetchValidation = true, fetchHintEntries = 32))
        assert(next.renameWidth == 2 && next.commitWidth == 2 && !next.fpEnabled)
        assert(!OooParams().wordSpanPacketPmp && !OooParams().parallelFetchValidation)
        assert(OooParams().fetchHintEntries == 8)
        assert(BoardSocConfig.boardParams("staged-gmac-ready", externalDdr = true, isa = "rv64gc").fpConfig.complete)
        intercept[IllegalArgumentException](OooParams(wordSpanPacketPmp = true))
        intercept[IllegalArgumentException](OooParams(parallelFetchValidation = true))
        intercept[IllegalArgumentException](OooParams(fetchHintEntries = 7))
    }
    test("UART domain is explicit and optional; timer remains in CPU domain") {
        val rtl = ChiselStage.emitCHIRRTL(new BoardSocTop(vivadoMemories = false,
            socClockHz = 100000000, externalDdr = true, timingProfile = "staged-gmac-ready",
            uartBaud = 460800, peripheralClockHz = 50000000))
        assert(rtl.contains("peripheralClock : Clock") && rtl.contains("RegisterClockDomainBridge"))
        assert(rtl.contains("connect timer.clock, clock"))
        val uartResets = rtl.linesIterator.filter(_.trim.startsWith("connect uart.reset,")).toSeq
        assert(uartResets.size == 1 && uartResets.head.contains(".destinationReset"),
            "async UART reset must not be overwritten by the CPU reset loop")
    }
}
