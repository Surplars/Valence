package ooo

import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Exact64 rollback plus four explicit CPU switches; physical MAC generics stay separate. */
private[ooo] object NearTermAProfile {
    val baseCommit = "8e9a36c18a699e8b64830a97bb197f9fc52458bf"
    val fields = Seq("fetchAcceptedPrefixValidation", "alignedFetchSinglePage", "factorCheckedNextAllowed", "localTaggedResponseReady")
    val additions = Seq("--fetch-accepted-prefix-validation", "--aligned-fetch-single-page", "--factor-checked-next-allowed", "--local-tagged-response-ready")
    val rollbackOptions = R3ReadLocalityProfile.onOptions
    val onOptions = rollbackOptions ++ additions
    val rollback = FpgaNextConfig.fromOptions(rollbackOptions.toSet, defaultSelected = false)
    val on = FpgaNextConfig.fromOptions(onOptions.toSet, defaultSelected = false)
    val originalProfileNames = PlacedTimingProfileBridge.publishedProfileNames ++ Seq(
        "fetchAddressBeforePmp", "queuedHeadSelection", "alignedNextLinePmp", "registerProbeLookup",
        "localAddressRanges", "memoryPreparationHeadMask", "directRank0MemorySourceIds",
        "fetchReadyDataClear", "retirementSlotIdentity", "localCacheReadSelection")
    val originalCoreNames = PlacedTimingProfileBridge.publishedCoreNames ++ Seq(
        "fetchAddressBeforePmp", "queuedHeadSelection", "alignedNextLinePmp", "memoryPreparationHeadMask",
        "directRank0MemorySourceIds", "fetchReadyDataClear", "retirementSlotIdentity")
    require(rollbackOptions.size == 64 && onOptions.size == 68 && onOptions.distinct.size == 68)
    Seq(rollbackOptions, onOptions).foreach(FpgaNextProfileOptions.validate)
    require(on.copy(fetchAcceptedPrefixValidation = false, alignedFetchSinglePage = false,
        factorCheckedNextAllowed = false, localTaggedResponseReady = false) == rollback,
        "only the four named new CPU fields may differ from exact64")
    require(on.coreParams.copy(fetchAcceptedPrefixValidation = false, alignedFetchSinglePage = false,
        factorCheckedNextAllowed = false, localTaggedResponseReady = false) == rollback.coreParams,
        "all original 168 CPU parameters must remain equal")
    require(on.cache == rollback.cache && on.ddr == rollback.ddr && on.storage == rollback.storage &&
        on.tags == rollback.tags && on.network == rollback.network &&
        on.floatingPointResources == rollback.floatingPointResources)
    for (c <- Seq(rollback, on)) {
        PlacedTimingProfileBridge.requireShape(c)
        require(!c.triSpeedRawClockHandoff && !c.heldAluIssueForwarding && c.productArity == 91 && c.coreParams.productArity == 174 &&
            c.cache.productArity == 23 && c.ddr.productArity == 9)
        require(PlacedTimingProfileBridge.historicalAFields(c).size == 88 &&
            PlacedTimingProfileBridge.historicalAFields(c.coreParams).size == 172)
    }
    def originalFields(p: Product): Map[String, Any] = {
        val original = p match {
            case _: FpgaNextConfig => originalProfileNames
            case _: OooParams => originalCoreNames
            case _ => throw new IllegalArgumentException("only the exact profile/core products may be projected")
        }
        val values = PlacedTimingProfileBridge.historicalAFields(p)
        require(fields.forall(n => values(n) == false), "only these four named false fields may be projected")
        original.map(n => n -> values(n)).toMap
    }
    val root = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent).takeWhile(_ != null)
        .find(p => Files.isRegularFile(p.resolve("build.mill"))).get
    val originalBytes = Files.readAllBytes(root.resolve("fpga/next/near-term-a-original-profile.json"))
    require(MessageDigest.getInstance("SHA-256").digest(originalBytes).map(b => f"${b & 0xff}%02x").mkString ==
        "787e1cd167a447b2215a642449d0ebb169e24ccc1ea83ba33f3f79a8372740a5", "original exact64 profile snapshot changed")
    val projected = PostedBoardConfiguration.document(rollback) ++ Map(
        "profile" -> originalFields(rollback), "core" -> originalFields(rollback.coreParams))
    require(PostedBoardConfiguration.json(projected) == new String(originalBytes, "UTF-8").trim,
        "rollback does not reproduce every original exact64 parameter")
    def requireOn(options: Seq[String], c: FpgaNextConfig): Unit = {
        FpgaNextProfileOptions.validate(options)
        require(options == onOptions && c == on, "exact ordered 64+4 ON options and complete constructor required")
    }
    val sourceBridge = Map("schema" -> "near-term-a-source-bridge-v1", "baseCommit" -> baseCommit,
        "baseTree" -> "d498b36d8da24d06e9143428a0b7c042c88dff66", "rollbackCpuOptions" -> 64,
        "candidateCpuOptions" -> 68, "originalCoreFields" -> 168, "candidateCoreFields" -> 174,
        "currentProfileFields" -> 91, "historicalACoreFields" -> 172, "historicalAProfileFields" -> 88,
        "compatibilityCoreTail" -> Seq("postedYoungerLoadSealDeferral", "heldAluIssueForwarding"),
        "compatibilityProfileTail" -> Seq("triSpeedRawClockHandoff", "postedYoungerLoadSealDeferral", "heldAluIssueForwarding"),
        "newDefaultOffFields" -> fields, "originalProfileSha256" -> "787e1cd167a447b2215a642449d0ebb169e24ccc1ea83ba33f3f79a8372740a5",
        "physicalMacGenericsSeparate" -> true, "qualificationInherited" -> false, "physicalQualification" -> false)
}
