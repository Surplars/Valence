package platform

import _root_.circt.stage.ChiselStage
import soc.platform._
import soc.ip.clock.ManagedPeripheralBank
import java.nio.file.{Files, Paths}

/** Explicit candidate only. Default production A1 admission remains disabled.
  * Real complete debug/network/fixed/rate owners; only PHY model timing differs.
  */
class CommonA1DynamicFixture(files: Seq[String], selected: Option[CommonA1ExperimentalSelection] = None)
    extends CommonMachinePlatform(CommonCpuProfile.A1Boot50, romFiles = files,
        hardwareClocks = false, independentDdrClock = true, independentTimebaseClock = true,
        independentDebugClock = true, runtimeDebugAdmission = true, runtimeNetworkAdmission = true,
        runtimeFixedQualification = true, runtimeControlQualification = true, runtimeFixedMac = true,
        runtimeRateControl = true, externalIrqsAbsent = true,
        testOnlyRateParams = Some(DynamicRoundtripTestParams.rates), performanceTelemetry = true,
        telemetryWindowCycles = 1024, experimentalA1Runtime = true, a1Experimental = selected) {
    require(CommonCpuProfile.A1Boot50.cmu == CommonCpuProfile.I1Boot50Dynamic.cmu &&
        CommonCpuProfile.A1Boot50.fpga.network == CommonCpuProfile.I1Boot50Dynamic.fpga.network,
        "shared runtime test bank must retain A1 CMU/network geometry")
    override protected def buildPeripheralBank(): ManagedPeripheralBank = new DynamicRoundtripTestBank
}
object CommonA1DynamicMain extends App {
    require(args.length >= 3 && args.length <= 5,
        "output bank0 bank1 [--experimental-a1-profile=full-r1|full-r1-m3 --compile-receipt=PATH]")
    val output = Paths.get(args(0)).toAbsolutePath.normalize
    require(!Files.exists(output), "fresh output directory required; never reuse another CPU microarchitecture")
    val options = args.drop(3)
    require(options.forall(option => option.startsWith("--experimental-a1-profile=") ||
        option.startsWith("--compile-receipt=")), "unknown A1 runtime emitter option")
    require(options.map(_.takeWhile(_ != '=')).distinct.length == options.length, "duplicate A1 runtime emitter option")
    val selected = options.find(_.startsWith("--experimental-a1-profile=")).map(option =>
        CommonA1ExperimentalSelection.named(option.stripPrefix("--experimental-a1-profile=")))
    val compileReceipt = options.find(_.startsWith("--compile-receipt=")).map(option =>
        Paths.get(option.stripPrefix("--compile-receipt=")).toAbsolutePath.normalize)
    require(selected.isEmpty || compileReceipt.nonEmpty, "candidate runtime emission requires bound compile receipt")
    val root = Paths.get(sys.props.getOrElse("chisel.project.root", ".")).toAbsolutePath.normalize
    val compileBinding = selected.map(_ => CommonCpuMicroarchitectureIdentity.verifyCompileReceipt(compileReceipt.get, root))
    val boundary = CommonCpuProfile.A1Boot50.boundary.copy(
        runtimeMaintenance = true, runtimeCancellation = true, runtimeInterruptHold = true)
    val identity = CommonCpuMicroarchitectureIdentity.build(CommonCpuProfile.A1Boot50, selected, boundary,
        experimentalRuntime = true)
    ChiselStage.emitSystemVerilogFile(new CommonA1DynamicFixture(args.slice(1, 3).toSeq, selected),
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
    compileBinding.foreach(binding => require(
        CommonCpuMicroarchitectureIdentity.verifyCompileReceipt(compileReceipt.get, root) == binding,
        "bound compile receipt changed during candidate runtime emission"))
    CommonCpuMicroarchitectureIdentity.write(output.resolve("microarchitecture-identity.json"), identity)
}
