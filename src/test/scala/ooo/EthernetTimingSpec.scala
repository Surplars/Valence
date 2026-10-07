package ooo

import org.scalatest.funsuite.AnyFunSuite
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class EthernetTimingSpec extends AnyFunSuite {
    test("CPU batch is three opt-in combinational changes, with FP defaults preserved") {
        val old = BoardSocConfig.timingParams("staged-gmac-ready")
        val next = BoardSocConfig.timingParams("staged-ethernet")
        assert(next == old.copy(balancedPacketPmp = true,
            compactMemoryOperandSelect = true, parallelMemoryAddressSum = true))
        assert(next.renameWidth == 2 && next.commitWidth == 2 && !next.fpEnabled)
        val defaults = OooParams()
        assert(!defaults.balancedPacketPmp && !defaults.compactMemoryOperandSelect &&
            !defaults.parallelMemoryAddressSum)
        assert(BoardSocConfig.boardParams("staged-ethernet", externalDdr = true,
            isa = "rv64gc").fpConfig.complete)
    }
    test("Ethernet control requires an explicit external domain and has synchronized IRQ reset") {
        intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new BoardSocTop(
            vivadoMemories = false, ethernetControl = true)))
        val rtl = ChiselStage.emitCHIRRTL(new BoardSocTop(vivadoMemories = false,
            socClockHz = 100000000, externalDdr = true, timingProfile = "staged-ethernet",
            uartBaud = 460800, peripheralClockHz = 125000000, ethernetControl = true))
        assert(rtl.contains("ethernetAxi") && rtl.contains("RegisterAxiLite"))
        assert(rtl.contains("connect timer.clock, clock"))
        assert(rtl.linesIterator.exists(line => line.trim.startsWith("connect ") &&
            line.contains("irq.resetIn,") && line.contains(".sourceReset")),
            rtl.linesIterator.filter(_.contains("resetIn")).mkString("\n"))
        val uartResets = rtl.linesIterator.filter(_.trim.startsWith("connect uart.reset,")).toSeq
        assert(uartResets.size == 1 && uartResets.head.contains(".destinationReset"))
    }
}
