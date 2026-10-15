package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Isolated76 only: historical73, repaired74 and frozen75 files remain unchanged. */
object SharedLru76Profile {
    val base = SharedFuture75Profile
    val contract = ujson.read(Files.readString(Paths.get("fpga/next/shared-lru76-profile.json")))
    require(contract("schema").str == "valence-shared-lru76-profile-v1")
    private val parentBytes = Files.readAllBytes(Paths.get("fpga/next/shared-future75-profile.json"))
    require(MessageDigest.getInstance("SHA-256").digest(parentBytes).map(b => f"${b & 0xff}%02x").mkString ==
        contract("parent75_sha256").str)
    val options = base.options :+ "--store-prefetch-lru-victim"
    require(options.size == 76 && options == contract("on_options").arr.map(_.str).toSeq)
    FpgaNextProfileOptions.validate(options)
    val on = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    require(on == base.on.copy(storePrefetchLruVictim = true))
    require(on.coreParams == base.on.coreParams && on.storage == base.on.storage)
    require(on.ddr == base.on.ddr && on.network == base.on.network)
    require(on.cache == base.on.cache.copy(storePrefetchLruVictim = true))
    ProfileAbi77.requireHistorical(on)
    require(ProfileAbi77.retained(on).size == 94 && ProfileAbi77.retained(on.coreParams).size == 177)
    require(ProfileAbi77.retainedNames(on) == contract("profile_fields").arr.map(_.str).toSeq &&
        ProfileAbi77.retainedNames(on.coreParams) == contract("core_fields").arr.map(_.str).toSeq)
    require(on.coreParams.sharedMemoryAddressState && on.issueWidth == 2 && on.cpuHz == 100000000)
    require(on.storePrefetchLruVictim && on.futureHomeWayReservation && on.cache.storePrefetchLruVictim)
    require(contract("physical_options") == base.contract("physical_options"))
    def transform(v: ujson.Value): ujson.Value = v match {
        case obj: ujson.Obj => ujson.Obj.from(obj.obj.toSeq.map { case (k, x) =>
            if (k == "storePrefetchLruVictim") { require(x == ujson.Bool(false)); k -> ujson.Bool(true) }
            else k -> transform(x)
        })
        case arr: ujson.Arr => ujson.Arr.from(arr.arr.map(transform))
        case scalar => scalar
    }
    for (key <- Seq("on_profile", "on_existing_audits", "on_timing_audit", "on_fabric"))
        require(contract(key) == transform(base.contract(key)), "unapproved76 contract change: " + key)
    require(TimingReady73Profile.document(on) == contract("on_profile"))
    def expected(key: String): ujson.Value = transform(base.expected(key))
    def requireOptions(actual: Seq[String]): Unit = require(actual == options)
    def write(out: Path): Unit = {
        ProfileAbi77.writeProfile(on, out)
        Files.writeString(out.resolve("options.txt"), options.mkString("", "\n", "\n"))
        ProfileAbi77.writeFieldOrder(on, out)
    }
}

object SharedLru76ConfigMain extends App {
    val p = SharedLru76Profile
    var rejected = 0
    def reject(body: => Unit): Unit = {
        var failed = false
        try { body } catch { case _: IllegalArgumentException => failed = true }
        require(failed); rejected += 1
    }
    reject { p.requireOptions(p.options.reverse) }
    reject { p.requireOptions(p.options.dropRight(1)) }
    reject { FpgaNextProfileOptions.validate(p.options :+ "--store-prefetch-lru-victim") }
    require(p.on.copy(storePrefetchLruVictim = false) == p.base.on)
    require(p.base.on.copy(futureHomeWayReservation = false) == AreaFourthResourceProfile.on)
    require(AreaFourthResourceProfile.on.copy(sharedMemoryAddressState = false) == TimingReady73Profile.on)
    for (default <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected))
        require(!default.storePrefetchLruVictim && !default.futureHomeWayReservation &&
            !default.sharedMemoryAddressState)
    println(s"PASS_SHARED_LRU76_CONFIG core=177 profile=94 options=76 negative=$rejected")
}

/** Inspect the actual constructed final Home, preserving fourth-resource witnesses. */
object SharedLru76ActualAudit {
    def capture(platform: MachinePlatform): Map[String, Any] = {
        val expected = SharedLru76Profile.on
        val home = platform.finalHome.get.asInstanceOf[MixedCoherentLineHome]
        val cache = platform.privateCache.get.asInstanceOf[NonBlockingCoherentLineCache]
        require(cache.shareStoreWriteData && cache.registerProbeLookup && cache.localReadSelection)
        val fields = cache.getClass.getDeclaredFields.filter(_.getType == classOf[CoherentCacheConcurrency])
        require(fields.length == 1, "actual cache concurrency absent/ambiguous")
        fields.head.setAccessible(true)
        val actualCache = fields.head.get(cache).asInstanceOf[CoherentCacheConcurrency]
        require(actualCache == expected.cache && actualCache.storePrefetchLruVictim &&
            actualCache.futureHomeWayReservation)
        require(home.futureWayReservation && home.sharedLookupMatch && home.memoryScheduleOverlap)
        require(platform.core.core.core.p == expected.coreParams)
        Map("schema" -> "shared-lru76-actual-v1", "sharedLookupMatch" -> home.sharedLookupMatch,
            "futureHomeWayReservation" -> home.futureWayReservation,
            "sharedStoreWriteData" -> cache.shareStoreWriteData,
            "storePrefetchLruVictim" -> actualCache.storePrefetchLruVictim,
            "cache" -> actualCache,
            "boundedMultiplierTagsAbsent" -> platform.core.core.core.backend.multiplier.tags.isEmpty,
            "sharedMemoryAddressState" -> platform.core.core.core.p.sharedMemoryAddressState,
            "qualificationInherited" -> false,
            "machineOptIn" -> (expected.coreParams.sharedMemoryAddressState &&
                expected.cache.futureHomeWayReservation && expected.cache.storePrefetchLruVictim),
            "futureHome" -> FutureHomeActualAudit.capture(platform, expected),
            "fourthResource" -> AreaFourthResourceAudit.capture(platform), "physicalQualification" -> false)
    }
}

object SharedLru76CpuMain extends App {
    require(args.length == 77)
    val p = SharedLru76Profile
    p.requireOptions(args.drop(1).toSeq)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh shared-lru76 CPU output required")
    p.write(out)
    var actual: Option[Map[String, Any]] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = FpgaNextBoardGsim.build(p.on, verifyConfiguration = true)
        val fields = dut.getClass.getDeclaredFields.filter(_.getType == classOf[MatchingManagedBoard])
        require(fields.length == 1)
        fields.head.setAccessible(true)
        val board = fields.head.get(dut).asInstanceOf[MatchingManagedBoard]
        actual = Some(SharedLru76ActualAudit.capture(board.platform))
        dut
    }, Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
    ProfileAbi77.normalizeMatching(out, p.expected("fabric"), p.on)
    require(ujson.read(Files.readString(out.resolve("actual-fabric.json"))) == p.expected("fabric"))
    val actualJson = ujson.read(PostedBoardConfiguration.json(actual.get))
    for ((key, value) <- p.contract("derived_resource_expectations").obj)
        require(actualJson(key) == value, "derived resource mismatch: " + key)
    Files.writeString(out.resolve("actual-shared-lru76.json"), actualJson.render(indent = 2) + "\n")
    println("PASS_SHARED_LRU76_ACTUAL_CPU core=177 profile=94 options=76 qualification_pending")
}
