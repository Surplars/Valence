package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

class CommonPeripheralConfigSpec extends AnyFunSuite {
    test("default peripheral selection retains the existing full platform") {
        val config = CommonPeripheralConfig()
        assert(config == CommonPeripheralConfig.jtagOption("on"))
        assert(config.features == CommonPlatformFeatures(true, true, true, true))
        assert(config.mmioRegions == CommonPlatformAbi.cpuMmioRegions(config.features))
        config.validateRuntime(runtimeDebugAdmission = true)
    }

    test("JTAG off removes only its fixed address slot without renumbering any remaining device") {
        val on = CommonPeripheralConfig()
        val off = CommonPeripheralConfig.jtagOption("off")
        assert(off.features == on.features.copy(jtagDownload = false))
        assert(off.mmioRegions == on.mmioRegions.filterNot(_.name == "jtag"))
        assert(on.mmioRegions.find(_.name == "jtag").exists(_.base == BigInt("10003000", 16)))
        assert(off.mmioRegions.forall(r => !r.overlaps(on.mmioRegions.find(_.name == "jtag").get)))
        off.validateRuntime(runtimeDebugAdmission = false)
    }

    test("disabled JTAG rejects runtime debug admission instead of bypassing its owner protocol") {
        val failure = intercept[IllegalArgumentException] {
            CommonPeripheralConfig(jtagDownload = false).validateRuntime(runtimeDebugAdmission = true)
        }
        assert(failure.getMessage.contains("requires the JTAG RAM-download endpoint"))
    }

    test("the user option is explicit on or off") {
        Seq("true", "false", "", "disabled").foreach { value =>
            intercept[IllegalArgumentException] { CommonPeripheralConfig.jtagOption(value) }
        }
    }
    test("ordinary DMA presence changes only its aperture and keeps positional defaults") {
        val on = CommonPeripheralConfig()
        val off = on.copy(memoryCopyDma = false)
        assert(CommonPlatformFeatures(false, false, false, false).memoryCopyDma)
        assert(CommonPeripheralConfig(false).memoryCopyDma)
        assert(off.features == on.features.copy(memoryCopyDma = false))
        assert(off.mmioRegions == on.mmioRegions.filterNot(_.name == "dma"))
        assert(CommonPlatformAbi.dmaBase == BigInt("10001000", 16) && CommonPlatformAbi.dmaBytes == 40)
        assert(CommonPlatformAbi.dmaInterruptSource == 4)
        assert(off.features.networkDma && off.features.ethernetControl && off.features.clockManagement)
    }

}
