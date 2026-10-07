package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.clock._
import soc.core.ooo.{BoardSocConfig, BoardSocTop}

class ClockManagementSpec extends AnyFunSuite {
    test("CMU is CPU-independent with explicit bounded capacity") {
        val fir = ChiselStage.emitCHIRRTL(new ClockManagementGsim)
        assert(fir.contains("PeripheralClockControl") && fir.contains("replies"))
        assert(!fir.contains("MachineCore") && !fir.contains("EthernetPacketDma"))
        assert(CmuTestConfig.params.presentMask == 15 && CmuTestConfig.params.gateableMask == 12)
    }
    test("protected AON, parent ordering and resource inventory reject unsafe configurations") {
        intercept[IllegalArgumentException] { CmuParams(1, Seq(ClockResource("AON", 1, canGate = true))) }
        intercept[IllegalArgumentException] { CmuParams(1, Seq(ClockResource("AON", 1, parent = 0))) }
        intercept[IllegalArgumentException] { ClockResource("INVALID_NAME", 1) }
        intercept[IllegalArgumentException] { ClockResource("OFF", 0, canGate = true, present = false) }
        intercept[IllegalArgumentException] { CmuParams(1, Seq(ClockResource("AON", 1),
            ClockResource("PARENT", 1, canGate = true), ClockResource("CHILD", 1, parent = 1))) }
        for (ddr <- Seq(false, true); eth <- Seq(false, true); periph <- Seq(0, 50000000)) {
            val config = CmuParams(50000000,
                BoardSocConfig.clockResources(50000000, 100000000, periph, ddr, 250000000, eth))
            assert(config.gateableMask == 0 && config.resources(2).parent == 1)
        }
    }
    test("both real MMIO router variants elaborate; physical backend uses synchronous BUFGCE") {
        assert(ChiselStage.emitCHIRRTL(new ClockManagementRouterGsim(false)).contains("CoreRegisterRouter"))
        assert(ChiselStage.emitCHIRRTL(new ClockManagementRouterGsim(true)).contains("ParallelRegisterRouter"))
        val fir = ChiselStage.emitCHIRRTL(new FpgaClockResources(CmuTestConfig.params))
        assert(fir.contains("BUFGCE") && fir.contains("CE_TYPE = \"SYNC\""))
        assert(fir.contains("PeripheralQuiesceAck"))
        assert(ChiselStage.emitCHIRRTL(new ClockManagementBoundary(CmuTestConfig.params))
            .contains("RegisterClockDomainBridge"))
    }
    test("production board CMU is optional with protected inventory and explicit external control") {
        val disabled = ChiselStage.emitCHIRRTL(new BoardSocTop(uartBaud = 115200))
        assert(!disabled.contains("ClockManagementBoundary") && !disabled.contains("io.alwaysOnClock"))
        val enabled = ChiselStage.emitCHIRRTL(new BoardSocTop(socClockHz = 100000000,
            uartBaud = 460800, timingProfile = "staged-fetch-feedback", externalDdr = true,
            peripheralClockHz = 50000000, ethernetControl = true, ethernetDma = true,
            clockManagementHz = 50000000,
            managedClockResources = Seq(ClockResource("AUX", 50000000, canGate = true))))
        assert(enabled.contains("ClockManagementBoundary") && enabled.contains("alwaysOnClock"))
        assert(enabled.contains("clockManagementRegisters") && enabled.contains("clockResources"))
        assert(enabled.contains("ParallelRegisterRouter"))
    }
}
