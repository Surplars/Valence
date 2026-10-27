package soc.core.ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.platform.CommonA1RebuildProfile

/** Reuse the frozen passive CPU observer and immutable guests. */
object GuardedNaturalDataPmpCpuGsimMain extends App {
    require(args.length == 2, "output-directory exact-profile")
    val control = "full-r1-m3-checked-flow-store-row-elastic-proof"
    require(Set(control, control + "-guarded-natural-pmp").contains(args(1)))
    val config = CommonA1RebuildProfile.named(args(1)).config
    require(config.guardedNaturalDataPmp == (args(1) != control))
    require(!config.registeredRawCertifiedFlow && !config.registeredDataTranslation && !config.factoredDataPmpRange)
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Full-resource unchanged elastic CPU observer; one guarded natural-data PMP candidate. No PPA/board claim. Profile=" + args(1) + "\n")
    ChiselStage.emitCHIRRTLFile(new RegisteredRawCertifiedCpuGsim(args(1)), Array("--target-dir", args(0)))
}
