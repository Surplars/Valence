package ooo

import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Pure constructor/CLI compatibility. In particular, 54 + head-drain is not
  * a CPU, GSIM, native RTL, board, or physical qualification.
  */
class HeadDrainConfigSpec extends AnyFunSuite {
    private val flag = "--predecoded-head-drain"
    private val root = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(path => Files.isRegularFile(path.resolve("build.mill"))).get
    private def sha(bytes: Array[Byte]): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).map(byte => f"${byte & 0xff}%02x").mkString
    private def options(name: String): Seq[String] = {
        val text = Files.readString(root.resolve("fpga/next/" + name))
        val list = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r.findFirstMatchIn(text).get.group(1)
        "\"([^\"]*)\"".r.findAllMatchIn(list).map(_.group(1)).toSeq
    }
    private val default52 = options("timing-batch-owner-row-profile.json")
    private val future54 = options("timing-batch-home-future-lru-profile.json")
    private val off = FpgaNextConfig.fromOptions(default52.toSet, defaultSelected = false)
    private def fields(p: Product): Map[String, Any] = p.productElementNames.zip(p.productIterator).toMap
    private def changes(before: Product, after: Product): Map[String, Any] =
        fields(after).filter { case (name, value) => fields(before)(name) != value }

    test("every generic preset and the independently frozen complete default52 stay default off") {
        val manifest = root.resolve("fpga/next/timing-batch-owner-row-profile.json")
        assert(sha(Files.readAllBytes(manifest)) ==
            "32063adb7dd598ea5fcd014eee71c02d599139a59bf69287598f780a35d6d923")
        assert(default52.size == 52 && default52.distinct.size == 52)
        val snapshot = root.resolve("fpga/next/timing-batch-head-drain-default52.json")
        assert(sha(Files.readAllBytes(snapshot)) ==
            "87edfc04e59fce76873b83c236d694bc10a503497ba0a9e06534cf91327b9622")
        val bridged = PostedBoardConfiguration.document(off) ++ Map(
            "profile" -> PlacedTimingProfileBridge.headDrainSnapshotFields(off), "core" -> PlacedTimingProfileBridge.headDrainSnapshotFields(off.coreParams))
        assert(PostedBoardConfiguration.json(bridged) == Files.readString(snapshot).trim)
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.FetchCaptureCandidate,
                FpgaNextConfig.TriSpeedCandidate, FpgaNextConfig.ControlCandidate, FpgaNextConfig.Selected,
                FpgaNextConfig.RegisteredPmpCandidate, off)) {
            HeadDrainActualAudit.requireShape(c)
            assert(!c.predecodedHeadDrain && !c.coreParams.predecodedHeadDrain)
            assert(!c.eagerFetchPrefixSelect && !c.coreParams.eagerFetchPrefixSelect)
        }
        assert(!OooParams().predecodedHeadDrain)
        assert(!BoardSocConfig.boardParams(BoardSocConfig.timingProfile).predecodedHeadDrain)
        assert(BoardSocConfig.boardParams(BoardSocConfig.timingProfile, predecodedHeadDrain = true)
            .predecodedHeadDrain)
    }

    test("default52 plus the flag changes only the complete profile and core Boolean") {
        val on = FpgaNextConfig.fromOptions(default52.toSet + flag, defaultSelected = false)
        HeadDrainActualAudit.requireShape(on)
        assert(on.predecodedHeadDrain && on.coreParams.predecodedHeadDrain)
        assert(on.copy(predecodedHeadDrain = false) == off)
        assert(on.coreParams.copy(predecodedHeadDrain = false) == off.coreParams)
        assert(changes(off, on) == Map("predecodedHeadDrain" -> true))
        assert(changes(off.coreParams, on.coreParams) == Map("predecodedHeadDrain" -> true))
        assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage &&
            on.tags == off.tags && on.network == off.network && on.floatingPointResources == off.floatingPointResources)
        assert(!on.futureHomeWayReservation && !on.storePrefetchLruVictim && !on.eagerFetchPrefixSelect)
    }

    test("future Home and LRU54 plus head-drain has complete static rollback to independent default52") {
        assert(future54 == default52 ++ Seq("--future-home-way-reservation", "--store-prefetch-lru-victim"))
        val options55 = future54 :+ flag
        assert(options55.size == 55 && options55.distinct.size == 55)
        FpgaNextProfileOptions.validate(options55)
        val before = FpgaNextConfig.fromOptions(future54.toSet, defaultSelected = false)
        val combined = FpgaNextConfig.fromOptions(options55.toSet, defaultSelected = false)
        HeadDrainActualAudit.requireShape(combined)
        assert(combined.predecodedHeadDrain && combined.futureHomeWayReservation && combined.storePrefetchLruVictim)
        assert(combined.coreParams.predecodedHeadDrain && combined.cache.futureHomeWayReservation &&
            combined.cache.storePrefetchLruVictim)
        assert(!combined.eagerFetchPrefixSelect && !combined.coreParams.eagerFetchPrefixSelect)
        assert(combined.copy(predecodedHeadDrain = false) == before)
        assert(combined.coreParams.copy(predecodedHeadDrain = false) == before.coreParams)
        assert(combined.cache == before.cache && combined.ddr == before.ddr)
        assert(changes(off, combined) == Map("predecodedHeadDrain" -> true,
            "futureHomeWayReservation" -> true, "storePrefetchLruVictim" -> true))
        assert(changes(off.coreParams, combined.coreParams) == Map("predecodedHeadDrain" -> true))
        assert(changes(off.cache, combined.cache) == Map("futureHomeWayReservation" -> true,
            "storePrefetchLruVictim" -> true))
        assert(combined.copy(predecodedHeadDrain = false, futureHomeWayReservation = false,
            storePrefetchLruVictim = false) == off)
        assert(combined.coreParams.copy(predecodedHeadDrain = false) == off.coreParams)
        assert(combined.cache.copy(futureHomeWayReservation = false, storePrefetchLruVictim = false) == off.cache)
        assert(combined.ddr == off.ddr && combined.storage == off.storage && combined.tags == off.tags &&
            combined.network == off.network && combined.floatingPointResources == off.floatingPointResources)
    }

    test("strict CLI rejects duplicate valued and misspelled Boolean switches") {
        FpgaNextProfileOptions.validate(default52 :+ flag)
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(default52 ++ Seq(flag, flag)) }
        for (value <- Seq("", "true", "false", "0", "1")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(default52 :+ (flag + "=" + value)) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(default52.toSet + (flag + "=" + value), false) }
        }
        for (invalid <- Seq(flag.dropRight(1), flag + "s", "--predecoded_head_drain")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(default52 :+ invalid) }
        }
        intercept[IllegalArgumentException] { OooParams(predecodedHeadDrain = true) }
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq("--reference", "--candidate", flag)) }
    }
}
