package soc.core.ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.platform.CommonA1RebuildProfile

/** Three exports, but only two fresh runtime DUTs: owner control and combined. */
object AdvisoryOwnerCpuGsimMain extends App {
    require(args.length == 2, "output-directory exact-profile")
    val baseline = CommonA1RebuildProfile.FullR1M3BufferedReturnFlow
    val owner = CommonA1RebuildProfile.FullR1M3OrderedOwnerReady
    val combined = CommonA1RebuildProfile.FullR1M3AdvisoryOwner
    require(Set(baseline.name, owner.name, combined.name).contains(args(1)))
    val config = CommonA1RebuildProfile.named(args(1)).config
    require(config.orderedLsuResponseReady == (args(1) != baseline.name))
    require(config.registeredAdvisoryExclusion == (args(1) == combined.name))
    require(config.bufferedReturnFlow && config.translatedResponseEmptyFlow &&
        config.reconstructIssueTokenIndex && config.bufferedThirdRankLoadProof)
    require(config.coreParams.robEntries == 16 && config.coreParams.tagBits == 64 &&
        config.coreParams.memoryEntries == 4)
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Two separately attributed runtime DUTs; OFF export must equal sealed 51422f5. " +
            "No extra execution/PRF/owner/proof capacity. Profile=" + args(1) + "\n")
    ChiselStage.emitCHIRRTLFile(new RegisteredRawCertifiedCpuGsim(args(1)), Array("--target-dir", args(0)))
}
