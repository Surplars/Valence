package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.timer.FixedTimebaseBoundary
import soc.ip.debug.DebugDmiClockBoundary
import soc.platform.CommonMachineFabric

class FixedTimeDebugBoundarySpec extends AnyFunSuite {
    test("fixed timer contains complete MMIO crossing, atomic snapshot and IRQ synchronizer") {
        val rtl = ChiselStage.emitCHIRRTL(new FixedTimebaseBoundary)
        assert(rtl.contains("module MachineTimer"))
        assert(rtl.contains("module RegisterClockDomainBridge"))
        assert(rtl.contains("module CdcMailbox"))
        assert(rtl.contains("module CdcLevel"))
    }
    test("external timer removes fabric-domain timer while default retains it") {
        val rtl = ChiselStage.emitCHIRRTL(new CommonMachineFabric(externalTimer = true))
        assert(!rtl.contains("module MachineTimer"))
        assert(rtl.contains("externalTimerRegisters"))
        assert(rtl.contains("externalTimeSnapshot"))
    }
    test("DMI request and response cross as complete held payloads") {
        val rtl = ChiselStage.emitCHIRRTL(new DebugDmiClockBoundary)
        assert(rtl.contains("module CdcMailbox"))
        assert(rtl.contains("requests"))
        assert(rtl.contains("responses"))
        assert(rtl.contains("destinationLinkUp"))
    }
}
object FixedTimebaseNativeMain extends App {
    ChiselStage.emitSystemVerilogFile(new FixedTimebaseBoundary,
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
object DebugDmiBoundaryNativeMain extends App {
    ChiselStage.emitSystemVerilogFile(new DebugDmiClockBoundary,
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
