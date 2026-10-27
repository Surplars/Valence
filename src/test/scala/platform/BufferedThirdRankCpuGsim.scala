package soc.core.ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.platform.CommonA1RebuildProfile

/** Matched current split-tag control and optional buffered third-rank supply observer. */
object BufferedThirdRankCpuGsimMain extends App {
    require(args.length == 2, "output-directory exact-profile")
    val control = "full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag"
    require(Set(control, control + "-buffered-third-rank").contains(args(1)))
    val config = CommonA1RebuildProfile.named(args(1)).config
    require(config.bufferedThirdRankLoadProof == (args(1) != control))
    require(config.splitLowTagAdvance && config.guardedNaturalDataPmp && config.elasticLoadProofSupply &&
        !config.registeredRawCertifiedFlow && !config.registeredDataTranslation && !config.factoredDataPmpRange)
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Matched split-tag control and buffered third-rank advisory proof supply. " +
            "Candidate-only passive source-lifetime observation; no PPA/board claim. Profile=" + args(1) + "\n")
    ChiselStage.emitCHIRRTLFile(new RegisteredRawCertifiedCpuGsim(args(1)), Array("--target-dir", args(0)))
}
