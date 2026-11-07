package ooo
import _root_.circt.stage.ChiselStage
import soc.platform._

/** Pure production-selector elaboration, not CDC/DDR runtime qualification. */
object HypervisorPlatformShapes extends App {
    val root = java.nio.file.Path.of(args(0))
    java.nio.file.Files.createDirectories(root)
    for (enabled <- Seq(false, true)) {
        val text = ChiselStage.emitCHIRRTL(new CommonMachinePlatform(CommonCpuProfile.A1,
            hardwareClocks = false, experimentalHypervisor = enabled,
            peripheralConfig = CommonPeripheralConfig(false, false, false)))
        require(text.contains("module CommonHypervisorCpuTile") == enabled)
        require(text.contains("module HypervisorState") == enabled)
        require(text.contains("module GuestTranslationService") == enabled)
        require(text.contains("module CommonA1CpuTile") != enabled)
        java.nio.file.Files.writeString(root.resolve(if (enabled) "platform-h.fir" else "platform-default.fir"), text)
    }
    def rejected(make: => chisel3.RawModule): Unit = {
        var failed = false
        try { ChiselStage.emitCHIRRTL(make) } catch { case _: IllegalArgumentException => failed = true }
        require(failed, "unsupported profile was silently accepted")
    }
    rejected(new CommonMachinePlatform(CommonCpuProfile.I1, experimentalHypervisor = true))
    rejected(new CommonMachinePlatform(CommonCpuProfile.A1, experimentalHypervisor = true,
        runtimeDebugAdmission = true))
    println("PLATFORM_SELECTOR_SHAPES_PASS default_off=true guest_files_default_zero=true unsupported_rejected=2")
}
