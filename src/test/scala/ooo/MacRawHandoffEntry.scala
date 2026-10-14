package ooo

import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** A platform-only extension; A's ordered 68 options and all 172 CPU values stay fixed. */
private[ooo] object MacRawHandoffEntry {
    val flag = "--tri-speed-raw-clock-handoff"
    val off = NearTermAProfile.on
    val options = NearTermAProfile.onOptions :+ flag
    val on = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    FpgaNextProfileOptions.validate(options)
    require(options.size == 69 && options.distinct.size == 69)
    require(!off.triSpeedRawClockHandoff && on.triSpeedRawClockHandoff)
    require(on.copy(triSpeedRawClockHandoff = false) == off,
        "only the named MAC platform field may differ from A")
    require(on.productArity == 91 && on.coreParams.productArity == 174)
    val originalPath = NearTermAProfile.root.resolve("fpga/next/near-term-a-before-mac-platform.json")
    val originalBytes = Files.readAllBytes(originalPath)
    require(java.security.MessageDigest.getInstance("SHA-256").digest(originalBytes)
        .map(b => f"${b & 0xff}%02x").mkString == "71150576981a2622c9458ba8a359b7112e4f04d3af5ef0b46fa1e1fcf860cf69", "original complete A profile changed")
    val offFields = off.productElementNames.zip(off.productIterator).toMap
    require(offFields("triSpeedRawClockHandoff") == false)
    val originalOff = PostedBoardConfiguration.document(off) +
        ("profile" -> PlacedTimingProfileBridge.historicalAFields(off)) +
        ("core" -> PlacedTimingProfileBridge.historicalAFields(off.coreParams))
    require(PostedBoardConfiguration.json(originalOff) == new String(originalBytes, "UTF-8").trim,
        "all original 88 A profile and 172 core fields must be byte-equivalent when platform OFF")
    require(on.coreParams == off.coreParams && on.cache == off.cache && on.ddr == off.ddr &&
        on.storage == off.storage && on.tags == off.tags && on.network == off.network &&
        on.floatingPointResources == off.floatingPointResources,
        "MAC handoff must preserve every CPU, cache, DDR, storage and capacity value")
}

/** Called on the actual full board during the next native export. Scala-only
  * object observations create no RTL taps and do not certify mapped topology.
  */
object MacRawHandoffEntryAudit {
    def capture(board: BoardSocTop, expected: FpgaNextConfig): Map[String, Any] = {
        require(board.triSpeedRawClockHandoff == expected.triSpeedRawClockHandoff,
            "actual BoardSocTop lost the RAW MAC handoff parameter")
        val bank = board.nativeBank.getOrElse(throw new IllegalArgumentException("managed bank missing"))
        require(bank.triSpeedRawClockHandoff == expected.triSpeedRawClockHandoff,
            "actual managed bank lost the RAW MAC handoff parameter")
        val actual = bank.instantiatedTriSpeedMac
        require(actual.isDefined == expected.experimentalTriSpeedEthernet,
            "actual tri-speed MAC presence differs from the platform")
        actual.foreach { mac =>
            require(mac.rawClockHandoff == expected.triSpeedRawClockHandoff &&
                mac.rawHandoff.isDefined == expected.triSpeedRawClockHandoff,
                "actual MAC/helper activation differs from the platform parameter")
            mac.rawHandoff.foreach { handoff =>
                require(handoff.rawRxPayload.getWidth == 11 && handoff.rxPayload.getWidth == 11 &&
                    handoff.rawTxByteStep.getWidth == 1 && handoff.txByteStep.getWidth == 1)
            }
        }
        val core = board.platform.core.core.core
        require(core.p == expected.coreParams && core.p.productArity == 174,
            "actual complete CPU constructor changed under the platform extension")
        Map("schema" -> "actual-mac-raw-handoff-platform-v1", "scope" -> "actual-constructor-only",
            "triSpeedRawClockHandoff" -> expected.triSpeedRawClockHandoff,
            "actualTriSpeedMac" -> actual.isDefined,
            "actualHandoffPresent" -> actual.exists(_.rawHandoff.isDefined),
            "profileFields" -> expected.productArity, "coreFields" -> core.p.productArity,
            "expectedRawFallingScalarBits" -> (if (expected.triSpeedRawClockHandoff) 12 else 0),
            "expectedManagedRxScalarBits" -> (if (expected.triSpeedRawClockHandoff) 11 else 0),
            "mappedFfCountVerified" -> false, "physicalQualification" -> false)
    }
}

object MacRawHandoffProfileMain extends App {
    require(args.length == 2, "usage: MacRawHandoffProfileMain fresh-directory off|on")
    val c = args(1) match {
        case "off" => MacRawHandoffEntry.off
        case "on" => MacRawHandoffEntry.on
        case _ => throw new IllegalArgumentException("choose off or on")
    }
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh constructor report required")
    PostedBoardConfiguration.write(c, out.toString)
    Files.writeString(out.resolve("mac-platform-contract.json"), PostedBoardConfiguration.json(Map(
        "schema" -> "mac-raw-handoff-platform-v1", "triSpeedRawClockHandoff" -> c.triSpeedRawClockHandoff,
        "baseNativeOptions" -> NearTermAProfile.onOptions, "addedPlatformOption" -> MacRawHandoffEntry.flag,
        "profileFields" -> c.productArity, "coreFields" -> c.coreParams.productArity,
        "allCoreValuesEqualA" -> (c.coreParams == NearTermAProfile.on.coreParams),
        "actualConstructorAuditRun" -> false, "physicalQualification" -> false)) + "\n")
}

class MacRawHandoffEntrySpec extends AnyFunSuite {
    test("MAC handoff changes one platform field and zero of 173 core fields") {
        assert(MacRawHandoffEntry.on.copy(triSpeedRawClockHandoff = false) == MacRawHandoffEntry.off)
        assert(MacRawHandoffEntry.on.coreParams == MacRawHandoffEntry.off.coreParams)
        assert(MacRawHandoffEntry.off.productElementNames.toSeq.takeRight(3) == Seq("triSpeedRawClockHandoff", "postedYoungerLoadSealDeferral", "heldAluIssueForwarding"))
        assert(!FpgaNextConfig.Selected.triSpeedRawClockHandoff)
        assert(!FpgaNextConfig.Candidate.triSpeedRawClockHandoff)
        assert(!FpgaNextConfig.Reference.triSpeedRawClockHandoff)
    }
    test("the platform flag requires tri-speed and exact nonduplicated spelling") {
        intercept[IllegalArgumentException] { FpgaNextConfig(triSpeedRawClockHandoff = true) }
        intercept[IllegalArgumentException] {
            FpgaNextProfileOptions.validate(MacRawHandoffEntry.options :+ MacRawHandoffEntry.flag)
        }
        for (value <- Seq("", "true", "false", "0", "1")) {
            val bad = MacRawHandoffEntry.flag + "=" + value
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(bad)) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set(bad), false) }
        }
    }
    test("historical projection only drops the named platform field when false") {
        assert(NearTermAProfile.originalFields(NearTermAProfile.rollback).size == 84)
        intercept[IllegalArgumentException] {
            NearTermAProfile.originalFields(NearTermAProfile.rollback.copy(triSpeedRawClockHandoff = true))
        }
        intercept[IllegalArgumentException] {
            PlacedTimingProfileBridge.publishedFields(FpgaNextConfig.TriSpeedCandidate.copy(triSpeedRawClockHandoff = true))
        }
    }
}
