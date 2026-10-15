package ooo

import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

object ProfileAbi77CompatibilityChecks {
    def run(): Unit = {
        val frozenHashes = Map(
        "timing-ready73-profile.json" -> "fc66ccb6e878d8d480c7c52ace4e512f55e06228c9995df63713c29db1e28ab7",
        "area-fourth-resource74-profile.json" -> "8313b7872ea1eb7f35ba862e9ea6fd6a6b8ae8529e93301dd3583b1e707aa66b",
        "shared-future75-profile.json" -> "a5779c5c6e858892fad99599ef8ffc80d041c91a3d26dfc9b1213f506b14c592",
        "shared-lru76-profile.json" -> "1a6748ca96aadd0bf77a4484a6eab1e981619414b326b0f0c8826a8059d2b8f5",
        "timing-closure-profile.json" -> "cac67b75762995a07baa65505bd8761e8ed49899d6402750b91b04544d7a44c9",
        "combined-cpu-profile.json" -> "5f515773787a45a6fba0854a0bdf040938b0caba7322ff90bc179de5661226ab")
        for ((name, expected) <- frozenHashes) {
            val bytes = Files.readAllBytes(Paths.get("fpga/next").resolve(name))
            require(MessageDigest.getInstance("SHA-256").digest(bytes).map(b => f"${b & 0xff}%02x").mkString == expected)
        }
        val q = ReadyStoreQuery77Profile
        ProfileAbi77.requireLive(q.on); ProfileAbi77.requireHistorical(q.off)
        require(q.on.productArity == 95 && q.on.coreParams.productArity == 178)
        require(ProfileAbi77.document(q.off) == q.parent("on_profile"))
        require(ujson.read(PostedBoardConfiguration.json(PostedBoardConfiguration.document(q.on)))("core")("pendingReadyStoreQuery").bool)
        for ((config, name) <- Seq(TimingReady73Profile.on -> "timing-ready73-profile.json",
                AreaFourthResourceProfile.on -> "area-fourth-resource74-profile.json",
                SharedFuture75Profile.on -> "shared-future75-profile.json",
                SharedLru76Profile.on -> "shared-lru76-profile.json")) {
            val expected = ujson.read(Files.readString(Paths.get("fpga/next").resolve(name)))("on_profile")
            require(ProfileAbi77.document(config) == expected)
            require(config.productArity == 95 && config.coreParams.productArity == 178)
        }
        require(TimingClosureProfile.document(TimingClosureProfile.on) == TimingClosureProfile.contract("on_profile"))
        TimingReady73ConfigMain.main(Array.empty[String])
        AreaFourthResourceConfigMain.main(Array.empty[String])
        SharedFuture75ConfigMain.main(Array.empty[String])
        SharedLru76ConfigMain.main(Array.empty[String])
        TimingClosureConfigMain.main(Array.empty[String])
        ReadyStoreQuery77ConfigMain.main(Array.empty[String])
        var rejected = 0
        def reject(body: => Unit): Unit = {
            var failed = false
            try body catch { case _: IllegalArgumentException => failed = true }
            require(failed, "malformed historical view was accepted")
            rejected += 1
        }
        val entries = q.off.coreParams.productElementNames.zip(q.off.coreParams.productIterator).toSeq
        reject { ProfileAbi77.retainedEntries(entries.reverse, "core") }
        reject { ProfileAbi77.retainedEntries(entries.dropRight(1), "core") }
        reject { ProfileAbi77.retainedEntries(entries :+ entries.last, "core") }
        reject { ProfileAbi77.retainedEntries(entries.updated(0, "unknown" -> entries.head._2), "core") }
        reject { ProfileAbi77.retainedEntries(entries.updated(entries.size - 1, ProfileAbi77.field -> "false"), "core") }
        reject { ProfileAbi77.retainedEntries(entries.updated(0, entries.head._1 -> "wrong-type"), "core") }
        reject { ProfileAbi77.retained(q.on.coreParams) }
        reject { ProfileAbi77.document(q.on) }
        reject { PlacedTimingProfileBridge.priorTimingClosureFields(TimingClosureProfile.on.coreParams) }
        require(PlacedTimingProfileBridge.priorTimingClosureFields(TimingClosureProfile.off.coreParams).size == 175)
        val expected = q.parent("on_profile")
        def liveDocument(): ujson.Value = ujson.read(PostedBoardConfiguration.json(PostedBoardConfiguration.document(q.off)))
        require(ProfileAbi77.report(liveDocument(), expected, "profile", q.off) == expected)
        reject { ProfileAbi77.report(liveDocument(), expected, "not-a-schema", q.off) }
        reject { ProfileAbi77.report(liveDocument(), expected, "profile", q.on) }
        val drift = liveDocument(); drift("core")("tagBits") = ujson.Num(32)
        reject { ProfileAbi77.report(drift, expected, "profile", q.off) }
        val unknown = liveDocument(); unknown("unexpected") = ujson.Bool(false)
        reject { ProfileAbi77.report(unknown, expected, "profile", q.off) }
        val missing = liveDocument(); missing("core").obj.remove("tagBits")
        reject { ProfileAbi77.report(missing, expected, "profile", q.off) }
        val enabled = liveDocument(); enabled("core")(ProfileAbi77.field) = ujson.Bool(true)
        reject { ProfileAbi77.report(enabled, expected, "profile", q.off) }
        val mistyped = liveDocument(); mistyped("core")(ProfileAbi77.field) = ujson.Str("false")
        reject { ProfileAbi77.report(mistyped, expected, "profile", q.off) }
        // Synthetic live metadata has independently fixed expected old and new counts/names.
        val oldMac = TimingReady73Profile.expected("on", "existing_audits")("mac")
        val liveMac = ujson.read(oldMac.render()); liveMac("coreFields") = ujson.Num(178); liveMac("profileFields") = ujson.Num(95)
        require(ProfileAbi77.report(liveMac, oldMac, "mac", q.off) == oldMac)
        val badCount = ujson.read(liveMac.render()); badCount("coreFields") = ujson.Num(177)
        reject { ProfileAbi77.report(badCount, oldMac, "mac", q.off) }
        val oldOrder = ujson.Obj("core" -> ujson.Arr.from(ProfileAbi77.coreNames76), "profile" -> ujson.Arr.from(ProfileAbi77.profileNames76))
        val liveOrder = ujson.Obj("core" -> ujson.Arr.from(ProfileAbi77.coreNames), "profile" -> ujson.Arr.from(ProfileAbi77.profileNames))
        require(ProfileAbi77.report(liveOrder, oldOrder, "field-order", q.off) == oldOrder)
        liveOrder("core") = ujson.Arr.from(ProfileAbi77.coreNames.reverse)
        reject { ProfileAbi77.report(liveOrder, oldOrder, "field-order", q.off) }
        // Independent pure-data fixture expansion from the SHA-pinned historical contract.
        // This is a serialization validator test, never a DUT behavioral oracle.
        def expanded(v: ujson.Value): ujson.Value = v match {
            case obj: ujson.Obj if obj.obj.keySet == Set("$timing_core") =>
                require(obj("$timing_core").str == "on"); ujson.read(q.parent("on_profile")("core").render())
            case obj: ujson.Obj => ujson.Obj.from(obj.obj.toSeq.map { case (k, x) => k -> expanded(x) })
            case arr: ujson.Arr => ujson.Arr.from(arr.arr.map(expanded))
            case scalar => scalar
        }
        def liveFixture(v: ujson.Value): ujson.Value = v match {
            case obj: ujson.Obj if obj.obj.keySet == ProfileAbi77.coreNames76.toSet ||
                    obj.obj.keySet == ProfileAbi77.profileNames76.toSet =>
                val copy = ujson.read(obj.render()); copy(ProfileAbi77.field) = ujson.Bool(false); copy
            case obj: ujson.Obj => ujson.Obj.from(obj.obj.toSeq.map { case (k, x) =>
                k -> (if (k == "coreFields") { require(x == ujson.Num(177)); ujson.Num(178) }
                else if (k == "profileFields") { require(x == ujson.Num(94)); ujson.Num(95) }
                else if (k == "coreNames") { require(x == ujson.Arr.from(ProfileAbi77.coreNames76)); ujson.Arr.from(ProfileAbi77.coreNames) }
                else if (k == "profileNames") { require(x == ujson.Arr.from(ProfileAbi77.profileNames76)); ujson.Arr.from(ProfileAbi77.profileNames) }
                else liveFixture(x)) })
            case arr: ujson.Arr => ujson.Arr.from(arr.arr.map(liveFixture))
            case scalar => scalar
        }
        val existing = expanded(q.parent("on_existing_audits"))
        val fixtures = Seq("profile" -> q.parent("on_profile"), "core" -> q.parent("on_profile")("core"),
            "fabric" -> expanded(q.parent("on_fabric")), "timing" -> expanded(q.parent("on_timing_audit")),
            "existing" -> existing, "held" -> existing("held"), "resident" -> existing("resident"), "mac" -> existing("mac"))
        val temporary = Files.createTempDirectory("query77-abi-boundaries-")
        try {
            for ((view, old) <- fixtures :+ ("field-order" -> oldOrder)) {
                val current = if (view == "field-order")
                    ujson.Obj("core" -> ujson.Arr.from(ProfileAbi77.coreNames), "profile" -> ujson.Arr.from(ProfileAbi77.profileNames))
                else liveFixture(old)
                require(ProfileAbi77.report(current, old, view, q.off) == old, "boundary positive: " + view)
                val path = temporary.resolve(view + ".json")
                val raw = current.render(indent = 2) + "\n"
                Files.writeString(path, raw)
                ProfileAbi77.normalizeFile(path, old, view, q.off)
                require(ujson.read(Files.readString(path)) == old)
                require(Files.readString(temporary.resolve(view + ".live77.json")) == raw)
            }
            val fabricExpected = expanded(q.parent("on_fabric"))
            val absent = liveFixture(fabricExpected); absent("heldAluIssueForwarding").obj.remove("core")
            reject { ProfileAbi77.report(absent, fabricExpected, "fabric", q.off) }
            val nested = liveFixture(fabricExpected); nested("timingClosure")("lsuSlots")(0)("tagBits") = ujson.Num(32)
            reject { ProfileAbi77.report(nested, fabricExpected, "fabric", q.off) }
            val extra = liveFixture(fabricExpected); extra("headDrain")(ProfileAbi77.field) = ujson.Bool(false)
            reject { ProfileAbi77.report(extra, fabricExpected, "fabric", q.off) }
            val collision = temporary.resolve("core.json")
            val liveCore = liveFixture(q.parent("on_profile")("core"))
            Files.writeString(collision, liveCore.render())
            Files.writeString(temporary.resolve("core.live77.json"), "{}")
            reject { ProfileAbi77.normalizeFile(collision, q.parent("on_profile")("core"), "core", q.off) }
        } finally {
            val files = Files.list(temporary)
            try files.forEach(p => Files.delete(p)) finally files.close()
            Files.delete(temporary)
        }
        require(rejected == 22, "all designated malformed projections must be reached")
        println(s"PASS_PROFILE_ABI77_COMPATIBILITY live=178/95 historical=177/94 negatives=$rejected frozen_json=6")
    }
}
object ProfileAbi77CompatibilityMain extends App { ProfileAbi77CompatibilityChecks.run() }
class ProfileAbi77CompatibilitySpec extends AnyFunSuite {
    test("live77 and exact false-only historical73-76 boundaries") { ProfileAbi77CompatibilityChecks.run() }
}
