package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

/** Structural checks only; GSIM separately verifies transactions and errors. */
class CommonPeripheralElaborationSpec extends AnyFunSuite {
    test("fabric JTAG choice removes the loader and its DMI ports, not unrelated peripherals") {
        for (enabled <- Seq(true, false)) {
            val config = CommonPeripheralConfig(jtagDownload = enabled)
            val rtl = ChiselStage.emitCHIRRTL(new CommonMachineFabric(features = config.features))
            assert(rtl.contains("module JtagRamLoader") == enabled)
            assert(rtl.contains("jtagDmi") == enabled)
            assert(rtl.contains("jtagLinkUp") == enabled)
            Seq("MemoryCopyDma", "EthernetPacketDma", "CommonInterruptFabric", "MixedCoherentLineHome")
                .foreach(name => assert(rtl.contains("module " + name)))
        }
    }

    test("platform rejects absent JTAG with runtime debug before constructing the hardware") {
        val failure = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CommonMachinePlatform(CommonCpuProfile.I1Performance300,
                independentDebugClock = true, runtimeDebugAdmission = true,
                peripheralConfig = CommonPeripheralConfig(jtagDownload = false)))
        }
        assert(failure.getMessage.contains("requires the JTAG RAM-download endpoint"))
    }
}

/** Explicit full-assembly structural export, never CPU execution or timing proof.
  * Baseline comparison uses the same emitter with only the new constructor
  * argument removed. Hardware clocks are disabled equally in both exports.
  */
object CommonJtagPlatformElaborationMain extends App {
    require(args.length == 2, "fresh output directory and on|off required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    val config = CommonPeripheralConfig.jtagOption(args(1))
    ChiselStage.emitCHIRRTLFile(new CommonMachinePlatform(CommonCpuProfile.A1, hardwareClocks = false,
        peripheralConfig = config), Array("--target-dir", args(0)))
}
