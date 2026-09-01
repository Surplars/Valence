package sim

import java.nio.file.Files
import java.nio.file.Path

import chisel3._
import _root_.circt.stage.ChiselStage
import difftest.DifftestModule
import soc._
import soc.config.DeviceTree
import soc.config.ISAProfiles
import soc.config.SoCFeatures
import soc.config.SoCProfiles

class SimTop extends IonSoC

// Explicit MCU emission target. Keeping this separate from SimTop lets tests
// and Makefile targets depend on a stable platform contract.
class SimTopMCU extends IonSoC(SoCProfiles.BareMetalMCU, ISAProfiles.RV64IMACB) {
    override def desiredName: String = "SimTop"
}
class SimTopICache extends IonSoC(SoCFeatures(iCache = true)) {
    override def desiredName: String = "SimTop"
}
class SimTopFirmware extends IonSoC(SoCProfiles.LinuxCapablePLIC, ISAProfiles.RV64IMACB) {
    override def desiredName: String = "SimTop"
}
class SimTopLinux extends IonSoC(SoCProfiles.LinuxBootPLIC, ISAProfiles.RV64IMACB) {
    override def desiredName: String = "SimTop"
}

object EmitHelper {
    def emit(top: => RawModule, targetDir: String = "build/rtl"): Unit = {
        ChiselStage.emitSystemVerilogFile(
            top,
            args = Array("--target-dir", targetDir),
            firtoolOpts = Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=enable")
        )
    }
}

object TopMain extends App {
    EmitHelper.emit(new SimTop, "build/rtl")
}

object McuTopMain extends App {
    EmitHelper.emit(new SimTopMCU, "build/rtl-mcu")
}

object ICacheTopMain extends App {
    EmitHelper.emit(new SimTopICache, "build/rtl-icache")
}

object FirmwareTopMain extends App {
    EmitHelper.emit(new SimTopFirmware, "build/rtl-firmware")
}

object LinuxTopMain extends App {
    EmitHelper.emit(new SimTopLinux, "build/rtl-linux")
}

object DeviceTreeMain extends App {
    val output = Path.of(args.headOption.getOrElse("simulator/build/ionsoc.dts"))
    val profile = args.lift(1).getOrElse("firmware")
    val extraBootargs = args.lift(2).getOrElse("")
    val dts = profile match {
        case "firmware" => DeviceTree.linuxCapableDts()
        case "linux"    => DeviceTree.linuxBootDts(extraBootargs)
        case other      => throw new IllegalArgumentException(s"unknown device-tree profile: $other")
    }
    Option(output.getParent).foreach(Files.createDirectories(_))
    Files.writeString(output, dts)
}

object DifftestTopMain extends App {
    EmitHelper.emit(
            DifftestModule.top(
                new IonSoCDifftest(
                SoCProfiles.BareMetalMCU.copy(mmu = true),
                ISAProfiles.RV64IMACB,
                injectTestStimulus = true,
                exitOnBareMetalSentinel = true
            )
        ),
        "build/rtl-difftest"
    )
}

object LinuxDifftestTopMain extends App {
    EmitHelper.emit(
        DifftestModule.top(
            new IonSoCDifftest(
                SoCProfiles.LinuxBootPLIC,
                ISAProfiles.RV64IMACB,
                injectTestStimulus = false,
                exitOnBareMetalSentinel = false
            )
        ),
        "build/rtl-difftest-linux"
    )
}
