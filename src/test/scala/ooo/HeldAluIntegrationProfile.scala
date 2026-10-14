package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** A's ordered 68 options plus one explicit default-OFF CPU option. */
private[ooo] object HeldAluIntegrationProfile {
    val sourceBaseCommit = "bb85d08bda18121b1b848fbbbd004af50f2cc504"
    val sourceBaseTree = "d1447e5e10179c9cc287c600d9aa36a2239128e2"
    val flag = "--held-alu-issue-forwarding"
    val offOptions = NearTermAProfile.onOptions
    val onOptions = offOptions :+ flag
    val off = FpgaNextConfig.fromOptions(offOptions.toSet, defaultSelected = false)
    val on = FpgaNextConfig.fromOptions(onOptions.toSet, defaultSelected = false)
    val historicalCoreNames = NearTermAProfile.originalCoreNames ++ NearTermAProfile.fields
    val historicalProfileNames = NearTermAProfile.originalProfileNames ++ NearTermAProfile.fields
    val coreTail = Seq("postedYoungerLoadSealDeferral", "heldAluIssueForwarding")
    val profileTail = Seq("triSpeedRawClockHandoff", "postedYoungerLoadSealDeferral", "heldAluIssueForwarding")
    require(offOptions.size == 68 && onOptions.size == 69 && onOptions.distinct.size == 69)
    Seq(offOptions, onOptions).foreach(FpgaNextProfileOptions.validate)
    require(on.copy(heldAluIssueForwarding = false) == off)
    require(on.coreParams.copy(heldAluIssueForwarding = false) == off.coreParams)
    require(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage &&
        on.tags == off.tags && on.network == off.network && on.floatingPointResources == off.floatingPointResources)
    for (c <- Seq(off, on)) {
        PlacedTimingProfileBridge.requireShape(c)
        require(c.productArity == 91 && c.coreParams.productArity == 174)
        require(!c.triSpeedRawClockHandoff && !c.postedYoungerLoadSealDeferral && c.fetchAcceptedPrefixValidation && c.alignedFetchSinglePage &&
            c.factorCheckedNextAllowed && c.localTaggedResponseReady)
    }
    require(!off.heldAluIssueForwarding && on.heldAluIssueForwarding)

    def historicalAFields(p: Product): Map[String, Any] = {
        val (original, tail) = p match {
            case _: FpgaNextConfig => (historicalProfileNames, profileTail)
            case _: OooParams => (historicalCoreNames, coreTail)
            case _ => throw new IllegalArgumentException("only complete named A profile/core products")
        }
        require(p.productElementNames.toSeq == original ++ tail, "complete product names/order differ")
        val values = p.productElementNames.zip(p.productIterator).toMap
        require(tail.forall(n => values(n) == false), "every named compatibility field must be Boolean false")
        original.map(n => n -> values(n)).toMap
    }
    val originalBytes = Files.readAllBytes(NearTermAProfile.root.resolve("fpga/next/near-term-a-before-mac-platform.json"))
    require(java.security.MessageDigest.getInstance("SHA-256").digest(originalBytes)
        .map(b => f"${b & 0xff}%02x").mkString == "71150576981a2622c9458ba8a359b7112e4f04d3af5ef0b46fa1e1fcf860cf69")
    val originalOff = PostedBoardConfiguration.document(off) ++ Map(
        "profile" -> historicalAFields(off), "core" -> historicalAFields(off.coreParams))
    require(PostedBoardConfiguration.json(originalOff) == new String(originalBytes, "UTF-8").trim,
        "every original A172/A88 value and nested fabric product must remain identical")

    def requireSide(side: String, options: Seq[String], c: FpgaNextConfig): Unit = {
        FpgaNextProfileOptions.validate(options)
        val expected = side match {
            case "off" => (offOptions, off)
            case "on" => (onOptions, on)
            case _ => throw new IllegalArgumentException("explicit off or on side required")
        }
        require(options == expected._1 && c == expected._2, "exact ordered options and complete constructor required")
    }
    def writeFieldOrder(c: FpgaNextConfig, directory: String): Unit = {
        PlacedTimingProfileBridge.requireShape(c)
        Files.writeString(Paths.get(directory, "actual-product-field-order.json"),
            PostedBoardConfiguration.json(Map("core" -> c.coreParams.productElementNames.toSeq,
                "profile" -> c.productElementNames.toSeq)) + "\n")
    }
    val sourceBridge = Map("schema" -> "held-alu-integration-source-bridge-v1",
        "sourceBaseCommit" -> sourceBaseCommit,
        "baseKind" -> "published-young-parent",
        "baseHardwareScalaBridgeSha256" -> "e0d5b9cf75fe832e089ef3997b11430467a69d49f3301fbde3771463ddfd71ea", "sourceBaseTree" -> sourceBaseTree,
        "historicalACommit" -> "767e7683f3d6f5bd1fee257735505b353500d2a5", "historicalCoreFields" -> 172, "historicalProfileFields" -> 88,
        "baseCoreFields" -> 173, "baseProfileFields" -> 90,
        "currentCoreFields" -> 174, "currentProfileFields" -> 91,
        "coreCompatibilityTail" -> coreTail, "profileCompatibilityTail" -> profileTail,
        "newCpuField" -> "heldAluIssueForwarding", "offOptionCount" -> 68, "onOptionCount" -> 69,
        "allFourAFlagsRemainTrue" -> true, "physicalMacHandoff" -> false,
        "qualificationInherited" -> false, "dynamicQualification" -> false, "physicalQualification" -> false)
}

object HeldAluIntegrationProfileMain extends App {
    require(args.length >= 2, "usage: HeldAluIntegrationProfileMain fresh-directory off|on exact-options")
    val options = args.drop(2).toSeq
    val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    HeldAluIntegrationProfile.requireSide(args(1), options, c)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh constructor destination required")
    PostedBoardConfiguration.write(c, out.toString)
    HeldAluIntegrationProfile.writeFieldOrder(c, out.toString)
    Files.writeString(out.resolve("held-alu-source-bridge.json"),
        PostedBoardConfiguration.json(HeldAluIntegrationProfile.sourceBridge) + "\n")
}
