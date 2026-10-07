package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.uart.UartConsole

class UartParamsSpec extends AnyFunSuite {
    test("UART baud reference stays within the single physical clock") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new UartConsole(clockHz = 45000000, referenceClockHz = 45000001))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new UartConsole(referenceClockHz = -1))
        }
        for ((hz, reference) <- Seq((45000000, 24000000), (50000000, 1843200))) {
            val fir = ChiselStage.emitCHIRRTL(new UartConsole(clockHz = hz, referenceClockHz = reference))
            assert(fir.contains("fifoEnabled") && fir.contains("rxTimeout") && fir.contains("rxVotes"))
        }
    }
    test("UART rejects unaligned or overflowing register windows and elaborates a relocated IP") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new UartConsole(1)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new UartConsole(BigInt(1) << 64)) }
        val rtl = ChiselStage.emitCHIRRTL(new UartConsole(BigInt("20000000", 16)))
        assert(rtl.contains("module UartConsole") && rtl.contains("rxMeta") && rtl.contains("rxSync"))
    }
}
