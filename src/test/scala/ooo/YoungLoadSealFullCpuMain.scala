package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.FpgaNextConfig

/** One explicit new ON model; retained published A supplies the OFF objects. */
object YoungLoadSealFullCpuMain extends App {
    require(args.length == 70, "usage: YoungLoadSealFullCpuMain fresh-directory exact-A68 plus one flag")
    val options = args.drop(1).toSeq
    val c = YoungLoadSealSourceBridge.candidate(options)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh output directory required")
    PostedBoardConfiguration.write(c, out.toString)
    YoungLoadSealSourceBridge.write(c, out.toString)
    Files.writeString(out.resolve("options.txt"), options.mkString("", "\n", "\n"))
    Files.writeString(out.resolve("young-load-seal-source-bridge.json"), PostedBoardConfiguration.json(Map(
        "schema" -> "young-load-seal-source-bridge-v1",
        "publishedCommit" -> "767e7683f3d6f5bd1fee257735505b353500d2a5",
        "publishedTree" -> "27d5fbd1c8d7863be9194020cf1db42a20c94751",
        "oldCoreFields" -> 172, "oldProfileFields" -> 88, "oldOptions" -> 68,
        "newCoreFields" -> c.coreParams.productArity, "newProfileFields" -> c.productArity, "newOptions" -> 69,
        "publishedYoungCoreFields" -> 173, "publishedYoungProfileFields" -> 90,
        "heldAluIssueForwarding" -> false, "residentMemoryPayloadReuse" -> false,
        "platformOnlyField" -> "triSpeedRawClockHandoff", "triSpeedRawClockHandoff" -> false,
        "newDefaultFalseField" -> "postedYoungerLoadSealDeferral",
        "headLoadAndAtomicBoundaryPreserved" -> true,
        "physicalQualification" -> false)) + "\n")
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true),
        Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
}
