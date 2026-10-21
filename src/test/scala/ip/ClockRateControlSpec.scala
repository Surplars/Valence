package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.clock._

/** Synthetic evidence flags ONLY for the component oracle, never production rates. */
object ClockRateFixtureParams {
    val cpu = ClockRateParams(timeoutCycles = 48, points = Seq(
        ClockRatePoint(50000000, true, true, true), ClockRatePoint(100000000, true, true, true),
        ClockRatePoint(150000000, true, true, true), ClockRatePoint(175000000, true, true, false)))
    val fabric = cpu.copy(maximumHz = 150000000, points = cpu.points.filter(_.hz <= 150000000))
}

class ClockRateControlSpec extends AnyFunSuite {
    test("legality, component tests and SoC qualification are separate") {
        assert(!ClockRatePoint(100000000, physicalLegal = true).allowed)
        assert(!ClockRatePoint(100000000, true, true, false).allowed)
        assert(ClockRatePoint(100000000, true, true, true).flags == 15)
        assert(ClockRateParams().points.isEmpty)
        intercept[IllegalArgumentException] { ClockRateParams(points = Seq(ClockRatePoint(51000000))) }
        intercept[IllegalArgumentException] { ClockRateParams(points = Seq.fill(2)(ClockRatePoint(50000000))) }
    }
    test("MMIO and actual complete-response CDC elaborate independently of CPU and MMCM") {
        val fir = ChiselStage.emitCHIRRTL(new ClockRateManagementBoundary(
            Seq(ClockRateFixtureParams.cpu, ClockRateFixtureParams.fabric)))
        assert(fir.contains("ClockRateControl") && fir.contains("RegisterClockDomainBridge"))
        assert(fir.contains("CdcMailbox") && fir.contains("sourceRetired"))
        assert(!fir.contains("MMCME4_ADV") && !fir.contains("CommonMachinePlatform"))
    }
}

object ClockRateComponentMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new ClockRateManagementBoundary(
        Seq(ClockRateFixtureParams.cpu, ClockRateFixtureParams.fabric)),
        Array("--target-dir", args(0)), firtoolOpts = Array("-disable-all-randomization", "-strip-debug-info",
            "-default-layer-specialization=disable", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
