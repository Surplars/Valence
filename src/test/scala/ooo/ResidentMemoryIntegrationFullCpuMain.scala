package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.FpgaNextConfig

/** Prepared entry for one new ON model; invocation requires coordinator release. */
object ResidentMemoryIntegrationFullCpuMain extends App {
    require(args.length == 71, "usage: ResidentMemoryIntegrationFullCpuMain fresh-directory exact-Young69 plus resident")
    val options = args.drop(1).toSeq
    val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    ResidentMemoryIntegrationProfile.requireSide("on", options, c)
    val output = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(output), "fresh ON output directory required")
    PostedBoardConfiguration.write(c, output.toString)
    ResidentMemoryIntegrationProfile.write(c, output.toString)
    Files.writeString(output.resolve("options.txt"), options.mkString("", "\n", "\n"))
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true),
        Array("--target-dir", output.toString))
    MatchingFabricAudit.write(output.toString)
}
