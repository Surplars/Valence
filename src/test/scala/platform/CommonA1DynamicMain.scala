package platform

import _root_.circt.stage.ChiselStage
import soc.platform._
import soc.ip.clock.ManagedPeripheralBank

/** Explicit candidate only. Default production A1 admission remains disabled.
  * Real complete debug/network/fixed/rate owners; only PHY model timing differs.
  */
class CommonA1DynamicFixture(files: Seq[String])
    extends CommonMachinePlatform(CommonCpuProfile.A1Boot50, romFiles = files,
        hardwareClocks = false, independentDdrClock = true, independentTimebaseClock = true,
        independentDebugClock = true, runtimeDebugAdmission = true, runtimeNetworkAdmission = true,
        runtimeFixedQualification = true, runtimeControlQualification = true, runtimeFixedMac = true,
        runtimeRateControl = true, externalIrqsAbsent = true,
        testOnlyRateParams = Some(DynamicRoundtripTestParams.rates), performanceTelemetry = true,
        telemetryWindowCycles = 1024, experimentalA1Runtime = true) {
    override protected def buildPeripheralBank(): ManagedPeripheralBank = new DynamicRoundtripTestBank
}
object CommonA1DynamicMain extends App {
    require(args.length == 3)
    ChiselStage.emitSystemVerilogFile(new CommonA1DynamicFixture(args.drop(1).toSeq),
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
