package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Untapped production adapter for matched isolated mapping, not whole-CPU timing. */
object GuardedNaturalDtaNativeMain extends App {
    require(args.length == 2, "output-directory exact-profile")
    val control = "full-r1-m3-checked-flow-store-row-elastic-proof"
    require(Set(control, control + "-guarded-natural-pmp").contains(args(1)))
    val config = CommonA1RebuildProfile.named(args(1)).config
    val p = config.coreParams
    require(config.guardedNaturalDataPmp == (args(1) != control))
    require(!p.registeredDataTranslation && !p.registeredRawCertifiedFlow && !p.factoredDataPmpRange)
    require(config.translationHitFlow && p.combinedCheckedDataFlow && p.elasticLoadProofSupply)
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), p)
    Files.writeString(out.resolve("scope.txt"),
        "Untapped production DataTranslationAdapter with identical stored capacities and ports. " +
        "Guarded mode intentionally rejects malformed standalone raw alignment; no CPU or physical timing claim. " +
        "Profile=" + args(1) + "\n")
    ChiselStage.emitCHIRRTLFile(new DataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = config.translationHitFlow, registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
        queuedHeadSelection = p.queuedHeadSelection, alignedNextLinePmp = p.alignedNextLinePmp,
        factorCheckedNextAllowed = p.factorCheckedNextAllowed), Array("--target-dir", args(0)))
}
