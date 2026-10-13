package ooo

import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Constructor and ordered-option checks only. The candidate is default52 plus
  * retirement intent with LRU, future Home reservation, and head-drain disabled.
  * These checks do not dynamically qualify any other legal parameter combination.
  */
class RetirementIntentBoardConfigSpec extends AnyFunSuite {
    private val flag = "--retirement-intent"
    private val root = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(path => Files.isRegularFile(path.resolve("build.mill"))).get
    private val manifest = root.resolve("fpga/next/timing-batch-owner-row-profile.json")
    private val manifestText = Files.readString(manifest)
    private val optionList = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r
        .findFirstMatchIn(manifestText).get.group(1)
    private val default52 = "\"([^\"]*)\"".r.findAllMatchIn(optionList).map(_.group(1)).toSeq
    private val candidate53 = default52 :+ flag
    private val off = FpgaNextConfig.fromOptions(default52.toSet, defaultSelected = false)
    private val on = FpgaNextConfig.fromOptions(candidate53.toSet, defaultSelected = false)
    private def fields(p: Product): Map[String, Any] = p.productElementNames.zip(p.productIterator).toMap
    private def changes(before: Product, after: Product): Map[String, Any] =
        fields(after).filter { case (name, value) => fields(before)(name) != value }

    test("published default52 is unchanged and retirement intent is appended default off") {
        val digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(manifest))
            .map(byte => f"${byte & 0xff}%02x").mkString
        assert(digest == "32063adb7dd598ea5fcd014eee71c02d599139a59bf69287598f780a35d6d923")
        assert(default52.size == 52 && default52.distinct.size == 52)
        PlacedTimingProfileBridge.requireShape(off)
        assert(off.productArity == 88 && off.productElementName(73) == "retirementIntent")
        assert(off.productElementName(72) == "predecodedHeadDrain")
        assert(off.coreParams.productArity == 172 && off.coreParams.productElementName(160) == "retirementIntent")
        assert(off.coreParams.productElementName(159) == "predecodedHeadDrain")
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.FetchCaptureCandidate,
                FpgaNextConfig.TriSpeedCandidate, FpgaNextConfig.ControlCandidate, FpgaNextConfig.Selected,
                FpgaNextConfig.RegisteredPmpCandidate, off)) {
            PlacedTimingProfileBridge.publishedFields(c)
            PlacedTimingProfileBridge.publishedFields(c.coreParams)
            assert(!c.retirementIntent && !c.coreParams.retirementIntent)
            assert(!c.predecodedHeadDrain && !c.coreParams.predecodedHeadDrain)
        }
        assert(!OooParams().retirementIntent && !OooParams().predecodedHeadDrain)
        assert(!BoardSocConfig.boardParams(BoardSocConfig.timingProfile).retirementIntent)
    }

    test("the exact candidate adds one option and changes only the complete profile and core Boolean") {
        assert(candidate53.size == 53 && candidate53.distinct.size == 53)
        assert(candidate53.filterNot(_ == flag) == default52)
        assert(candidate53.toSet -- default52.toSet == Set(flag))
        assert(default52.toSet -- candidate53.toSet == Set.empty[String])
        assert(on.retirementIntent && on.coreParams.retirementIntent)
        assert(on.copy(retirementIntent = false) == off)
        assert(on.coreParams.copy(retirementIntent = false) == off.coreParams)
        assert(changes(off, on) == Map("retirementIntent" -> true))
        assert(changes(off.coreParams, on.coreParams) == Map("retirementIntent" -> true))
        assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage &&
            on.tags == off.tags && on.network == off.network && on.floatingPointResources == off.floatingPointResources)
        assert(!on.storePrefetchLruVictim && !on.cache.storePrefetchLruVictim)
        assert(!on.futureHomeWayReservation && !on.cache.futureHomeWayReservation)
        assert(!on.predecodedHeadDrain && !on.coreParams.predecodedHeadDrain)
        assert(!on.eagerFetchPrefixSelect && !on.coreParams.eagerFetchPrefixSelect)
        assert(on.name == off.name + "-retirement-intent")
        assert(on.issueWidth == 2 && on.coreParams.robEntries == 16 && on.coreParams.physicalRegs == 48)
        assert(on.coreParams.memoryEntries == 4 && on.dataTranslationEntries == 16)
    }

    test("the production board parameter constructor forwards the explicit Boolean without enabling drain") {
        val before = off.coreParams
        val after = on.coreParams
        assert(after.retirementIntent && !after.predecodedHeadDrain)
        assert(after == before.copy(retirementIntent = true))
    }

    test("the public ordered option validator accepts the candidate without depending on switch position") {
        for (ordered <- Seq(candidate53, flag +: default52, default52.reverse :+ flag)) {
            FpgaNextProfileOptions.validate(ordered)
            assert(FpgaNextConfig.fromOptions(ordered.toSet, defaultSelected = false) == on)
        }
        FpgaNextProfileOptions.validate(default52)
    }

    test("the public ordered option validator rejects duplicate unknown and valued switches") {
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(candidate53 :+ flag) }
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(candidate53 :+ default52.head) }
        for (invalid <- Seq("--unknown", flag.dropRight(1), flag + "s", "--retirement_intent")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(default52 :+ invalid) }
        }
        for (value <- Seq("", "true", "false", "0", "1")) {
            val valued = flag + "=" + value
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(default52 :+ valued) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(default52.toSet + valued, false) }
        }
        intercept[IllegalArgumentException] {
            FpgaNextProfileOptions.validate(Seq("--reference", "--candidate", flag))
        }
    }
}
