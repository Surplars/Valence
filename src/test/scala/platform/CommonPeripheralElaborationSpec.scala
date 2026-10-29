package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

/** Structural checks only; GSIM separately verifies transactions and errors. */
class CommonPeripheralElaborationSpec extends AnyFunSuite {
    test("fabric JTAG choice removes the loader and its DMI ports, not unrelated peripherals") {
        for (enabled <- Seq(true, false); memoryCopyDma <- Seq(true, false); network <- Seq(true, false)) {
            val config = CommonPeripheralConfig(jtagDownload = enabled, memoryCopyDma = memoryCopyDma, network = network)
            val rtl = ChiselStage.emitCHIRRTL(new CommonMachineFabric(features = config.features))
            assert(rtl.contains("module JtagRamLoader") == enabled)
            assert(rtl.contains("jtagDmi") == enabled)
            assert(rtl.contains("jtagLinkUp") == enabled)
            assert(rtl.contains("module MemoryCopyDma") == memoryCopyDma)
            assert(rtl.contains("module EthernetPacketDma") == network)
            assert(rtl.contains("ethernetRegisters") == network)
            assert(rtl.contains("ethernetStreams") == network)
            Seq("CommonInterruptFabric", "MixedCoherentLineHome")
                .foreach(name => assert(rtl.contains("module " + name)))
        }
    }

    test("zero producers and absent optional line DMA elaborate without dangling ports") {
        for (enabled <- Seq(true, false)) {
            val rtl = ChiselStage.emitCHIRRTL(new CommonMachineFabric(
                features = CommonPlatformFeatures(memoryCopyDma = enabled),
                fpga = soc.core.ooo.FpgaNextConfig.Selected.copy(dmaLineTransfers = true, dmaLineEntries = 4)))
            assert(rtl.contains("module MemoryCopyDma") == enabled)
            assert(rtl.contains("module DmaRegisterDataAdapter") == enabled)
            assert(!rtl.contains("module RegisterArbiter"))
            assert(rtl.contains("dmaLine :") == enabled)
            assert(rtl.contains("module MixedCoherentLineHome"))
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
    test("managed bank network option removes real MAC and ports while preserving UART and CMU") {
        for (network <- Seq(true, false)) {
            val config = CommonSocConfig(CommonCpuProfile.A1,
                peripherals = CommonPeripheralConfig(network = network))
            val rtl = ChiselStage.emitCHIRRTL(new soc.ip.clock.ManagedPeripheralBank(config.cmu,
                config.profile.cpuHz, config.profile.uartHz, hardwareClocks = false,
                triSpeedEthernet = network, triSpeedTxFrameSlots = (if (network) 2 else 1),
                networkEnabled = network))
            assert(rtl.contains("module TriSpeedManagedGmac") == network)
            assert(rtl.contains("module ManagedUart") && rtl.contains("module ClockManagementBoundary"))
            for (port <- Seq("rawTxClock", "rawRxClock", "gmacRegisters", "streams", "gmiiTxData", "mdioIn"))
                assert(rtl.contains(port + " :") == network)
        }
    }

    test("platform rejects absent network with runtime admission before constructing the hardware") {
        val failure = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CommonMachinePlatform(CommonCpuProfile.I1Performance300,
                independentDebugClock = true, runtimeDebugAdmission = true, runtimeNetworkAdmission = true,
                peripheralConfig = CommonPeripheralConfig(network = false)))
        }
        assert(failure.getMessage.contains("requires the GMAC and packet DMA"))
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

/** Full static platform pair: conditional port/instance proof, not CPU execution. */
object CommonNetworkPlatformElaborationMain extends App {
    require(args.length == 2 && Set("on", "off").contains(args(1)), "fresh output directory and on|off required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonMachinePlatform(CommonCpuProfile.A1, hardwareClocks = false,
        peripheralConfig = CommonPeripheralConfig(network = args(1) == "on")), Array("--target-dir", args(0)))
}
