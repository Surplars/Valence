package ooo

import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Named append-only bridge to actual785; dynamic qualification is recorded separately. */
object RetirementSlotProfile {
    val addedCoreNames = Seq("memoryPreparationHeadMask", "directRank0MemorySourceIds",
        "fetchReadyDataClear", "retirementSlotIdentity", "fetchAcceptedPrefixValidation",
        "alignedFetchSinglePage", "factorCheckedNextAllowed", "localTaggedResponseReady", "postedYoungerLoadSealDeferral", "heldAluIssueForwarding", "residentMemoryPayloadReuse")
    val actual59CoreNames = PlacedTimingProfileBridge.publishedCoreNames ++
        Seq("fetchAddressBeforePmp", "queuedHeadSelection", "alignedNextLinePmp")
    val config = PlacedTimingProfile.on
    val p = config.coreParams
    private val root = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(path => Files.isRegularFile(path.resolve("build.mill"))).get
    private val frozen = root.resolve("fpga/next/retirement-slot-actual59-core.json")
    private val bytes = Files.readAllBytes(frozen)
    private val hash = MessageDigest.getInstance("SHA-256").digest(bytes).map(b => f"${b & 0xff}%02x").mkString
    require(hash == "c75c67e8308fe8c30593a691a5101ed2bdf549dd19ca5129b76a07f2af2ccef4")
    require(actual59CoreNames.size == 164 && actual59CoreNames.distinct.size == 164)

    def original164(defaultFalse: OooParams): Map[String, Any] = {
        require(defaultFalse.productElementNames.toSeq == actual59CoreNames ++ addedCoreNames,
            "only the eleven named appended core fields may bridge actual785")
        val fields = defaultFalse.productElementNames.zip(defaultFalse.productIterator).toMap
        require(addedCoreNames.forall(name => PlacedTimingProfileBridge.literalFalse(fields(name))),
            "all eleven named additions must be false before historical projection")
        val original = actual59CoreNames.map(name => name -> fields(name)).toMap
        require(PostedBoardConfiguration.json(original) == Files.readString(frozen).trim,
            "one or more original164 core values differ from actual785")
        original
    }
    original164(p)
    require(p.productArity == 175 && p.retirementIntent && p.predecodedHeadDrain && p.tagBits == 64)
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.commitWidth == 2 && p.completionWidth == 2)

    def requirePair(off: OooParams, on: OooParams): Unit = {
        original164(off)
        require(!off.retirementSlotIdentity && on.retirementSlotIdentity)
        require(on.copy(retirementSlotIdentity = false) == off,
            "the complete OFF/ON products may differ only in retirementSlotIdentity")
        // Normalize only the authorized candidate flag before the strict false projection.
        original164(on.copy(retirementSlotIdentity = false))
    }
    def writeParameters(directory: String): Unit = {
        val path = Paths.get(directory)
        Files.createDirectories(path)
        val off = RetirementSlotTestProfile.off
        val on = RetirementSlotTestProfile.on
        requirePair(off, on)
        for ((side, actual) <- Seq("off" -> off, "on" -> on)) {
            Files.writeString(path.resolve(s"actual-core-$side.json"), PostedBoardConfiguration.json(actual) + "\n")
        }
        Files.writeString(path.resolve("actual-core-original164.json"), PostedBoardConfiguration.json(original164(off)) + "\n")
        Files.writeString(path.resolve("actual-retirement-slot.json"), PostedBoardConfiguration.json(Map(
            "schema" -> "retirement-slot-integrated-v1", "coreFields" -> p.productArity,
            "originalCoreFields" -> 164, "namedDefaultFalseAdditions" -> addedCoreNames,
            "referenceLocalSwitch" -> off.retirementSlotIdentity, "candidateLocalSwitch" -> on.retirementSlotIdentity,
            "retirementIntent" -> p.retirementIntent, "profileOptionCount" -> PlacedTimingProfile.candidateOptions.size,
            "globalReferenceAuthority" -> "assertion-only-on", "profileFlagUnified" -> true)) + "\n")
        Files.writeString(path.resolve("native-options.txt"), PlacedTimingProfile.candidateOptions.mkString("", "\n", "\n"))
    }
}
