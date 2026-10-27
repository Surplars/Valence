package soc.core.ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.platform.CommonA1RebuildProfile

/** One new combined DUT; the disabled export is compared to sealed 7daf119. */
object BufferedReturnFlowCpuGsimMain extends App {
    require(args.length == 2, "output-directory exact-profile")
    val control = CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof
    val candidate = CommonA1RebuildProfile.FullR1M3BufferedReturnFlow
    require(Set(control.name, candidate.name).contains(args(1)))
    val config = CommonA1RebuildProfile.named(args(1)).config
    require(config.bufferedReturnFlow == (args(1) == candidate.name))
    require(config.reconstructIssueTokenIndex == config.bufferedReturnFlow &&
        config.translatedResponseEmptyFlow == config.bufferedReturnFlow)
    require(config.bufferedThirdRankLoadProof && config.coreParams.robEntries == 16 &&
        config.coreParams.tagBits == 64)
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Buffered return empty flow + fixed-row issue index; one new CPU, no early completion or added credits. " +
            "Candidate-only passive observation. Profile=" + args(1) + "\n")
    ChiselStage.emitCHIRRTLFile(new RegisteredRawCertifiedCpuGsim(args(1)), Array("--target-dir", args(0)))
}
