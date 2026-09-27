package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.uart.UartConsole

class UartParamsSpec extends AnyFunSuite {
    test("UART rejects unaligned or overflowing register windows and elaborates a relocated IP") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new UartConsole(1)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new UartConsole(BigInt(1) << 64)) }
        val rtl = ChiselStage.emitCHIRRTL(new UartConsole(BigInt("20000000", 16)))
        assert(rtl.contains("module UartConsole") && rtl.contains("rxMeta") && rtl.contains("rxSync"))
    }
}
