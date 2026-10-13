package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.FpgaNextConfig

/** One explicit new ON model; retained published A supplies the OFF objects. */
object YoungLoadSealFullCpuMain extends App {
    require(args.length == 70, "usage: YoungLoadSealFullCpuMain fresh-directory exact-A68 plus one flag")
    val options = args.drop(1).toSeq
    val flag = "--posted-younger-load-seal-deferral"
    require(options == (NearTermAProfile.onOptions :+ flag), "only the exact append-only A68+1 options are supported")
    FpgaNextProfileOptions.validate(options)
    val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    require(c.postedYoungerLoadSealDeferral &&
        c.copy(postedYoungerLoadSealDeferral = false) == NearTermAProfile.on &&
        c.coreParams.copy(postedYoungerLoadSealDeferral = false) == NearTermAProfile.on.coreParams,
        "candidate changed an original A parameter")
    require(!c.triSpeedRawClockHandoff && c.productArity == 90 && c.coreParams.productArity == 173)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh output directory required")
    PostedBoardConfiguration.write(c, out.toString)
    Files.writeString(out.resolve("options.txt"), options.mkString("", "\n", "\n"))
    Files.writeString(out.resolve("young-load-seal-source-bridge.json"), PostedBoardConfiguration.json(Map(
        "schema" -> "young-load-seal-source-bridge-v1",
        "publishedCommit" -> "767e7683f3d6f5bd1fee257735505b353500d2a5",
        "publishedTree" -> "27d5fbd1c8d7863be9194020cf1db42a20c94751",
        "oldCoreFields" -> 172, "oldProfileFields" -> 88, "oldOptions" -> 68,
        "newCoreFields" -> 173, "newProfileFields" -> 90, "newOptions" -> 69,
        "platformOnlyField" -> "triSpeedRawClockHandoff", "triSpeedRawClockHandoff" -> false,
        "newDefaultFalseField" -> "postedYoungerLoadSealDeferral",
        "headLoadAndAtomicBoundaryPreserved" -> true,
        "physicalQualification" -> false)) + "\n")
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true),
        Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
}
