package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Exact source compatibility with the published Young 173/90 products.
  * Only the named Boolean-false held field is projected; no execution qualification is inherited.
  */
object YoungLoadSealSourceBridge {
    val flag = "--posted-younger-load-seal-deferral"
    val heldField = "heldAluIssueForwarding"
    val historicalCoreNames = PlacedTimingProfileBridge.historicalACoreNames :+ "postedYoungerLoadSealDeferral"
    val historicalProfileNames = PlacedTimingProfileBridge.historicalAProfileNames ++
        Seq("triSpeedRawClockHandoff", "postedYoungerLoadSealDeferral")
    def historicalFields(p: Product): Map[String, Any] = {
        val old = p match {
            case _: FpgaNextConfig => historicalProfileNames
            case _: OooParams => historicalCoreNames
            case _ => throw new IllegalArgumentException("only exact Young profile/core products may be projected")
        }
        require(p.productElementNames.toSeq == old :+ heldField, "complete Young product names/order changed")
        val values = p.productElementNames.zip(p.productIterator).toMap
        require(values(heldField) match { case value: Boolean => !value; case _ => false },
            "historical Young projection requires named Boolean-false heldAluIssueForwarding")
        old.map(name => name -> values(name)).toMap
    }
    def requireCompatible(c: FpgaNextConfig): Unit = {
        PlacedTimingProfileBridge.requireShape(c)
        require(historicalFields(c).size == 90 && historicalFields(c.coreParams).size == 173)
    }
    def candidate(options: Seq[String]): FpgaNextConfig = {
        require(options == NearTermAProfile.onOptions :+ flag, "only exact ordered A68 plus Young is supported")
        FpgaNextProfileOptions.validate(options)
        val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
        requireCompatible(c)
        require(c.postedYoungerLoadSealDeferral && !c.triSpeedRawClockHandoff &&
            c.copy(postedYoungerLoadSealDeferral = false) == NearTermAProfile.on &&
            c.coreParams.copy(postedYoungerLoadSealDeferral = false) == NearTermAProfile.on.coreParams,
            "candidate changed an original A parameter")
        c
    }
    def document(c: FpgaNextConfig): Map[String, Any] = {
        requireCompatible(c)
        PostedBoardConfiguration.document(c) ++ Map(
            "profile" -> historicalFields(c), "core" -> historicalFields(c.coreParams))
    }
    def write(c: FpgaNextConfig, directory: String): Unit = {
        requireCompatible(c)
        Files.createDirectories(Paths.get(directory))
        Files.writeString(Paths.get(directory, "published-young-projection.json"),
            PostedBoardConfiguration.json(document(c)) + "\n")
        Files.writeString(Paths.get(directory, "young-held-false-source-bridge.json"), PostedBoardConfiguration.json(Map(
            "schema" -> "young-held-false-source-bridge-v1", "publishedYoungCommit" ->
                "bb85d08bda18121b1b848fbbbd004af50f2cc504", "oldCoreFields" -> 173, "oldProfileFields" -> 90,
            "currentCoreFields" -> c.coreParams.productArity, "currentProfileFields" -> c.productArity,
            "projectedDefaultFalseField" -> heldField, "heldAluIssueForwarding" -> false,
            "coreFieldOrder" -> c.coreParams.productElementNames.toSeq,
            "profileFieldOrder" -> c.productElementNames.toSeq,
            "historicalCoreFieldOrder" -> historicalCoreNames, "historicalProfileFieldOrder" -> historicalProfileNames,
            "qualificationInherited" -> false, "physicalQualification" -> false)) + "\n")
    }
}
