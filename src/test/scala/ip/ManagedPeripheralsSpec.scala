package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.clock._
import soc.core.ooo.BoardSocTop

class ManagedPeripheralsSpec extends AnyFunSuite {
    test("managed bank includes real UART, frames, counters and reply ownership") {
        val fir = ChiselStage.emitCHIRRTL(new ManagedPeripheralBank(ManagedPeripheralTestConfig.params))
        for (name <- Seq("BUFGCE", "UartConsole", "GmiiFrameTx", "GmiiFrameRx", "CdcCounterBank",
            "EthernetDmaFrameAdapter", "ClockRegisterAdmission", "RegisterClockDomainBridge"))
            assert(fir.contains(name))
        assert(!fir.contains("MachineCore") && !fir.contains("axi_ethernet"))
        assert(ManagedPeripheralTestConfig.params.gateableMask == 0x68)
        assert(ManagedPeripheralSupport.wakeDelay(50000000, 100000000, 50000000) == 64)
        assert(ManagedPeripheralSupport.wakeDelay(125000000, 100000000, 50000000) == 128)
    }
    test("production BoardSoc connects one CMU owner, UART and packet DMA without vendor MAC") {
        val fir = ChiselStage.emitCHIRRTL(new BoardSocTop(socClockHz = 100000000, uartBaud = 460800,
            timingProfile = "staged-fetch-feedback", externalDdr = true, peripheralClockHz = 50000000,
            ethernetControl = true, ethernetDma = true, clockManagementHz = 50000000,
            managedPeripherals = true))
        assert(fir.contains("ManagedPeripheralBank") && fir.contains("EthernetPacketDma"))
        assert(!fir.contains("RegisterAxiLite") && !fir.contains("io.ethernetAxi"))
        assert(fir.contains("externalUartRegisters") && fir.contains("nativeGmac"))
    }
    test("single-clock model never emits a fake physical gate") {
        val fir = ChiselStage.emitCHIRRTL(new ManagedPeripheralGsim)
        assert(!fir.contains("BUFGCE") && fir.contains("PeripheralWakeDelay"))
        intercept[IllegalArgumentException] { ManagedPeripheralSupport.wakeDelay(125000000, 100000000, 1000) }
    }
}
