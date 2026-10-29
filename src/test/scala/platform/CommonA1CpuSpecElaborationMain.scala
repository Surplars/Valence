package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.platform._

/** Explicit structural export. This does not execute a CPU or measure performance. */
object CommonA1CpuSpecElaborationMain extends App {
    require(args.length == 2, "fresh output directory and default|2|4 required")
    val output = Paths.get(args(0))
    require(!Files.exists(output), "fresh output directory required")
    val spec = if (args(1) == "default") None else Some(CommonA1CpuSpec.lsuOption(args(1)))
    val profile = CommonCpuProfile.A1
    ChiselStage.emitCHIRRTLFile(new CommonMachinePlatform(profile, hardwareClocks = false,
        cpuSpec = spec), Array("--target-dir", output.toString))
    CommonCpuMicroarchitectureIdentity.write(output.resolve("microarchitecture-identity.json"),
        CommonCpuMicroarchitectureIdentity.build(profile, None, profile.boundary, cpuSpec = spec))
}
