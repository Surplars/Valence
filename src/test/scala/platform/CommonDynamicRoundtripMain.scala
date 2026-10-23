package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.ip.clock._
import soc.ip.ethernet._
import soc.ip.dma.NetworkDmaConfig
import soc.platform._

/** The same diagnostic software-parameter policy as the board candidate.
  * Only PHY startup timing/model are fixture-specific, never qualification flags.
  */
object DynamicRoundtripTestParams {
    val rates = CommonDiagnosticRateProfile.domains
}
class DynamicRoundtripTestMac(config: NetworkDmaConfig)
    extends TriSpeedManagedGmac(cpuHz = 125000000, hardwareClocks = false,
        networkDmaConfig = config, txFrameSlots = 2, runtimeAdmission = true,
        runtimeControlPark = true, exportContinuousClock = true) {
    override def desiredName: String = "TriSpeedManagedGmac"
    override protected def buildPhyManager(): Rtl8211fPhyManager =
        new Rtl8211fPhyManager(125000000, startupCycles = 256, pollCycles = 512, runtimePark = true)
    dontTouch(linkUp)
    dontTouch(mediaPending)
}
class DynamicRoundtripTestBank
    extends ManagedPeripheralBank(CommonCpuProfile.I1Boot50Dynamic.cmu, cpuHz = 50000000,
        hardwareClocks = false, networkDmaConfig = CommonCpuProfile.I1Boot50Dynamic.fpga.network,
        triSpeedEthernet = true, triSpeedTxFrameSlots = 2, sourceClockHz = 50000000,
        rateDomains = Some(DynamicRoundtripTestParams.rates), runtimeAdmission = true,
        runtimeControlPark = true, runtimeFixedMac = true, runtimeRateControl = true, performanceTelemetry = true) {
    override def desiredName: String = "ManagedPeripheralBank"
    override protected def buildTriSpeedMac(): TriSpeedManagedGmac =
        new DynamicRoundtripTestMac(CommonCpuProfile.I1Boot50Dynamic.fpga.network)
    dontTouch(rateStatus.get)
    dontTouch(rateSafety.get)
}
class CommonDynamicRoundtripFixture(files: Seq[String])
    extends CommonMachinePlatform(CommonCpuProfile.I1Boot50Dynamic, romFiles = files,
        hardwareClocks = false, independentDdrClock = true, independentTimebaseClock = true,
        independentDebugClock = true, runtimeDebugAdmission = true, runtimeNetworkAdmission = true,
        runtimeFixedQualification = true, runtimeControlQualification = true, runtimeFixedMac = true,
        runtimeRateControl = true, externalIrqsAbsent = true,
        testOnlyRateParams = Some(DynamicRoundtripTestParams.rates), performanceTelemetry = true,
        telemetryWindowCycles = 1024) {
    override protected def buildPeripheralBank(): ManagedPeripheralBank = new DynamicRoundtripTestBank
}
object CommonDynamicRoundtripMain extends App {
    require(args.length == 3)
    ChiselStage.emitSystemVerilogFile(new CommonDynamicRoundtripFixture(args.drop(1).toSeq),
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
