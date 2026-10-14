package ooo

import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Source preparation for one tentative Young69 + resident CPU candidate.
  * The original measured Young product is 173/89, before the raw-MAC field.
  * Source compatibility is checked separately from any future execution gate.
  */
private[ooo] object ResidentMemoryIntegrationProfile {
    val sourceBaseTree = "f3dcb88dd4adb981b5cabe605610f8187aaaa0eb"
    val field = "residentMemoryPayloadReuse"
    val flag = "--resident-memory-payload-reuse"
    val offOptions = NearTermAProfile.onOptions :+ YoungLoadSealSourceBridge.flag
    val onOptions = offOptions :+ flag
    val off = FpgaNextConfig.fromOptions(offOptions.toSet, defaultSelected = false)
    val on = FpgaNextConfig.fromOptions(onOptions.toSet, defaultSelected = false)
    val historicalCoreNames = PlacedTimingProfileBridge.historicalACoreNames :+ "postedYoungerLoadSealDeferral"
    val historicalProfileNames = PlacedTimingProfileBridge.historicalAProfileNames :+ "postedYoungerLoadSealDeferral"
    val currentCoreNames = historicalCoreNames ++ Seq("heldAluIssueForwarding", field)
    val currentProfileNames = PlacedTimingProfileBridge.historicalAProfileNames ++
        Seq("triSpeedRawClockHandoff", "postedYoungerLoadSealDeferral", "heldAluIssueForwarding", field)
    private val root = NearTermAProfile.root
    private val reference = root.resolve("simulator/gsim/resident_memory_integration/reference-young69.json")
    private val referenceOrder = root.resolve("simulator/gsim/resident_memory_integration/reference-young69-field-order.json")
    private def pinned(path: java.nio.file.Path, expected: String): String = {
        val bytes = Files.readAllBytes(path)
        val hash = MessageDigest.getInstance("SHA-256").digest(bytes).map(b => f"${b & 0xff}%02x").mkString
        require(hash == expected, "immutable measured Young reference changed: " + path.getFileName)
        new String(bytes, "UTF-8").trim
    }
    val referenceJson = pinned(reference, "d251587fae19feb796e00f8e80b9cd25649d564f006c221b54f8ab08b9fbfc83")
    private val referenceOrderJson = pinned(referenceOrder, "5dbfc47d8a8490e99da18c36915964b0f0ded73a8d31d9bb99744750c0d1048f")
    require(PostedBoardConfiguration.json(Map("core" -> historicalCoreNames,
        "profile" -> historicalProfileNames)) == referenceOrderJson,
        "complete historical Young product order differs from retained source")

    /** Pure projection boundary; exact current names and literal false extras are mandatory. */
    def historicalFields(kind: String, names: Seq[String], values: Map[String, Any]): Map[String, Any] = {
        val (current, old, removed) = kind match {
            case "core" => (currentCoreNames, historicalCoreNames, Seq("heldAluIssueForwarding", field))
            case "profile" => (currentProfileNames, historicalProfileNames,
                Seq("triSpeedRawClockHandoff", "heldAluIssueForwarding", field))
            case _ => throw new IllegalArgumentException("only complete core/profile products may be projected")
        }
        require(names == current && names.distinct.size == names.size && values.keySet == current.toSet,
            "unknown, missing, reordered or substituted current product field")
        require(removed.forall(n => PlacedTimingProfileBridge.literalFalse(values(n))),
            "only named literal Boolean-false compatibility fields may be removed")
        require(values("postedYoungerLoadSealDeferral") match { case b: Boolean => b; case _ => false },
            "measured Young projection must retain true younger-load seal deferral")
        old.map(n => n -> values(n)).toMap
    }
    def historicalFields(p: Product): Map[String, Any] = {
        val kind = p match {
            case _: FpgaNextConfig => "profile"
            case _: OooParams => "core"
            case _ => throw new IllegalArgumentException("only exact profile/core products may be projected")
        }
        historicalFields(kind, p.productElementNames.toSeq, p.productElementNames.zip(p.productIterator).toMap)
    }
    def historicalDocument(c: FpgaNextConfig): Map[String, Any] = {
        PlacedTimingProfileBridge.requireShape(c)
        val projected = PostedBoardConfiguration.document(c) ++ Map(
            "profile" -> historicalFields(c), "core" -> historicalFields(c.coreParams))
        requireHistoricalDocument(projected)
        projected
    }
    def requireHistoricalDocument(document: Map[String, Any]): Unit =
        require(PostedBoardConfiguration.json(document) == referenceJson,
            "one or more complete original Young scalar, typed or nested values changed")

    require(offOptions.size == 69 && onOptions.size == 70 && onOptions.distinct.size == 70)
    Seq(offOptions, onOptions).foreach(FpgaNextProfileOptions.validate)
    require(on.copy(residentMemoryPayloadReuse = false) == off &&
        on.coreParams.copy(residentMemoryPayloadReuse = false) == off.coreParams,
        "resident is the only current OFF/ON parameter difference")
    require(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage && on.tags == off.tags &&
        on.network == off.network && on.floatingPointResources == off.floatingPointResources)
    for (c <- Seq(off, on)) {
        PlacedTimingProfileBridge.requireShape(c)
        require(c.productElementNames.toSeq == currentProfileNames && c.coreParams.productElementNames.toSeq == currentCoreNames)
        require(c.productArity == 92 && c.coreParams.productArity == 175 &&
            c.postedYoungerLoadSealDeferral && !c.heldAluIssueForwarding && !c.triSpeedRawClockHandoff)
    }
    require(!off.residentMemoryPayloadReuse && on.residentMemoryPayloadReuse)
    historicalDocument(off)

    def requireSide(side: String, options: Seq[String], c: FpgaNextConfig): Unit = {
        FpgaNextProfileOptions.validate(options)
        val expected = side match {
            case "off" => (offOptions, off)
            case "on" => (onOptions, on)
            case _ => throw new IllegalArgumentException("explicit off or on side required")
        }
        require(options == expected._1 && c == expected._2, "exact ordered options and complete constructor required")
    }
    val sourceBridge = Map("schema" -> "resident-memory-integration-source-v1",
        "sourceBaseTree" -> sourceBaseTree, "sourceBaseKind" -> "retained-corrected-B-r2-local-snapshot",
        "sourceCommitConfirmed" -> false, "referenceChoiceFinal" -> false,
        "measuredReference" -> "Young69", "historicalCoreFields" -> 173, "historicalProfileFields" -> 89,
        "mergedYoungCoreFields" -> 173, "mergedYoungProfileFields" -> 90,
        "currentCoreFields" -> 175, "currentProfileFields" -> 92,
        "offOptionCount" -> 69, "onOptionCount" -> 70, "newDefaultFalseField" -> field,
        "postedYoungerLoadSealDeferral" -> true, "heldAluIssueForwarding" -> false,
        "triSpeedRawClockHandoff" -> false, "qualificationInherited" -> false,
        "dynamicQualification" -> false, "physicalQualification" -> false)
    def write(c: FpgaNextConfig, directory: String): Unit = {
        PlacedTimingProfileBridge.requireShape(c)
        require(c == off || c == on, "only the exact tentative resident pair may be reported")
        val path = Paths.get(directory)
        Files.createDirectories(path)
        Files.writeString(path.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(Map(
            "core" -> c.coreParams.productElementNames.toSeq, "profile" -> c.productElementNames.toSeq)) + "\n")
        Files.writeString(path.resolve("resident-memory-source-bridge.json"), PostedBoardConfiguration.json(sourceBridge) + "\n")
        // Only the proven current OFF product is eligible for historical projection.
        Files.writeString(path.resolve("reference-young-off-projection.json"),
            PostedBoardConfiguration.json(historicalDocument(off)) + "\n")
    }
}

object ResidentMemoryIntegrationProfileMain extends App {
    require(args.length >= 2, "usage: ResidentMemoryIntegrationProfileMain fresh-directory off|on exact-options")
    val options = args.drop(2).toSeq
    val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    ResidentMemoryIntegrationProfile.requireSide(args(1), options, c)
    val output = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(output), "fresh constructor output directory required")
    PostedBoardConfiguration.write(c, output.toString)
    ResidentMemoryIntegrationProfile.write(c, output.toString)
}
