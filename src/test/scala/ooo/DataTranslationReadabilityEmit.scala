package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Small production-DTA emissions for source-only configuration/API equivalence.
  * No passive taps, CPU model, memory service or architectural oracle is introduced.
  */
object DataTranslationReadabilityEmit extends App {
    require(args.length == 1, "output-directory")
    val output = Paths.get(args(0))
    Files.createDirectories(output)

    case class Case(name: String, params: OooParams, hitFlow: Boolean)
    val independent = for (canonical <- Seq(false, true); factoring <- Seq(false, true)) yield {
        val p = PendingStoreProofFixture.params().copy(
            registeredCanonicalStoreEvent = canonical,
            dataNextLinePrefetch = true, factorCheckedNextAllowed = factoring)
        Case(s"canonical-${if (canonical) 1 else 0}-factoring-${if (factoring) 1 else 0}", p, false)
    }
    val frozen = Case("frozen-checked", PendingStoreProofFixture.params().copy(
        registeredCanonicalStoreEvent = true, frozenStoreCheckedFlow = true), false)
    val profiles = Seq(
        "certified" -> CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
        "coexisting" -> CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
        "nomination" -> CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5)
    val cases = independent ++ Seq(frozen) ++ profiles.map { case (name, profile) =>
        Case(name, profile.config.coreParams, profile.config.translationHitFlow)
    }
    require(cases.size == 8 && cases.map(_.name).distinct.size == 8)
    for (entry <- cases) {
        val directory = output.resolve(entry.name)
        Files.createDirectories(directory)
        val p = entry.params
        val parameters = p.productElementNames.zip(p.productIterator).map { case (name, value) =>
            s"$name=$value"
        }.mkString("", "\n", "\n")
        Files.writeString(directory.resolve("parameters.txt"), parameters)
        Files.writeString(directory.resolve("constructor.txt"),
            s"entries=8\nregisterCheckedRequests=true\ntranslationHitFlow=${entry.hitFlow}\n" +
            s"usePublishedPmpChanges=false\nqueuedHeadSelection=${p.queuedHeadSelection}\n" +
            s"alignedNextLinePmp=${p.alignedNextLinePmp}\nregisterNextLineDecision=false\n" +
            s"certifiedLoadIngress=${p.certifiedLoadIngress}\n")
        ChiselStage.emitCHIRRTLFile(new DataTranslationAdapter(p, registerCheckedRequests = true,
            translationHitFlow = entry.hitFlow,
            queuedHeadSelection = p.queuedHeadSelection, alignedNextLinePmp = p.alignedNextLinePmp,
            certifiedLoadIngress = p.certifiedLoadIngress), Array("--target-dir", directory.toString))
        println(s"DTA_EMIT_OK ${entry.name}")
    }
}
