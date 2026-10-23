package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.clock._
import soc.platform.CommonDiagnosticRateProfile

class SoftwareClockRateSpec extends AnyFunSuite {
    test("software parameter admission never claims qualification or a hardware whitelist") {
        val domains = CommonDiagnosticRateProfile.domains
        assert(domains.map(_.maximumHz) == Seq(300000000L, 250000000L))
        assert(domains.forall(p => p.softwareParameters && p.points.isEmpty && p.minimumHz == 10000000L))
        assert(domains.forall(_.admission == ClockRateAdmission.Diagnostic))
        val candidate = ClockRatePoint(100000000, diagnosticCandidate = true)
        assert(!candidate.allowed && candidate.flags == 16)
        assert(!ClockRateParams().admitted(candidate))
        assert(ClockRateParams(admission = ClockRateAdmission.Diagnostic).pointFlags(candidate) == 48)
        assert(ClockRatePoint(100000000, true, true, true).flags == 15)
        assert(ClockRateNativeProfile.encode(50000000L).contains(BigInt("14280a", 16)))
        assert(ClockRateNativeProfile.encode(100000000L).contains(BigInt("0a280a", 16)))
        assert(ClockRateNativeProfile.encode(175000000L).nonEmpty)
        (10000000L to 300000000L by 5000000L).foreach { hz =>
            val tuple = ClockRateNativeProfile.encode(hz).get
            val m = (tuple >> 8) & 255; val o = (tuple >> 16) & 255
            assert(m >= 32 && m <= 62 && o >= 3 && o <= 128)
            assert(25000000L * m == BigInt(hz) * o)
        }
        assert(ClockRateNativeProfile.encode(100000001L).isEmpty)
    }
    test("ordered telemetry router remains optional") {
        val disabled = ChiselStage.emitCHIRRTL(new ClockRateRegisterRouter())
        val enabled = ChiselStage.emitCHIRRTL(new ClockRateRegisterRouter(telemetry = true))
        assert(!disabled.contains("telemetryRegisters"))
        assert(enabled.contains("telemetryRegisters"))
    }
}

object SoftwareClockRateMain extends App {
    require(args.length == 2 && Set("diagnostic", "strict").contains(args(1)))
    val domains = CommonDiagnosticRateProfile.domains.map(p =>
        if (args(1) == "strict") p.copy(admission = ClockRateAdmission.QualifiedOnly) else p)
    ChiselStage.emitSystemVerilogFile(new ClockRateManagementBoundary(domains),
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
