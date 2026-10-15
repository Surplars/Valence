package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Separate preparation only. Historical73 and repaired74 contracts remain unchanged. */
object SharedFuture75Profile {
    val base = AreaFourthResourceProfile
    val contract = ujson.read(Files.readString(Paths.get("fpga/next/shared-future75-profile.json")))
    require(contract("schema").str == "valence-shared-future75-profile-v1")
    private val parentBytes = Files.readAllBytes(Paths.get("fpga/next/area-fourth-resource74-profile.json"))
    require(MessageDigest.getInstance("SHA-256").digest(parentBytes).map(b => f"${b & 0xff}%02x").mkString ==
        contract("parent74_sha256").str)
    val options = base.options :+ "--future-home-way-reservation"
    require(options.size == 75 && options == contract("on_options").arr.map(_.str).toSeq)
    FpgaNextProfileOptions.validate(options)
    val on = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    require(on == base.on.copy(futureHomeWayReservation = true))
    require(on.coreParams == base.on.coreParams && on.storage == base.on.storage)
    require(on.ddr == base.on.ddr && on.network == base.on.network)
    require(on.cache == base.on.cache.copy(futureHomeWayReservation = true))
    ProfileAbi77.requireHistorical(on)
    require(ProfileAbi77.retained(on).size == 94 && ProfileAbi77.retained(on.coreParams).size == 177)
    require(ProfileAbi77.retainedNames(on) == contract("profile_fields").arr.map(_.str).toSeq &&
        ProfileAbi77.retainedNames(on.coreParams) == contract("core_fields").arr.map(_.str).toSeq)
    require(on.coreParams.sharedMemoryAddressState && on.issueWidth == 2 && on.cpuHz == 100000000)
    require(contract("physical_options") == base.contract("physical_options"))
    def transform(v: ujson.Value): ujson.Value = v match {
        case obj: ujson.Obj => ujson.Obj.from(obj.obj.toSeq.map { case (k, x) =>
            if (k == "futureHomeWayReservation") { require(x == ujson.Bool(false)); k -> ujson.Bool(true) }
            else k -> transform(x)
        })
        case arr: ujson.Arr => ujson.Arr.from(arr.arr.map(transform))
        case scalar => scalar
    }
    for (key <- Seq("on_profile", "on_existing_audits", "on_timing_audit", "on_fabric"))
        require(contract(key) == transform(base.contract(key)), "unapproved75 contract change: " + key)
    require(TimingReady73Profile.document(on) == contract("on_profile"))
    def expected(key: String): ujson.Value = transform(base.expected(key))
    def requireOptions(actual: Seq[String]): Unit = require(actual == options)
    def write(out: Path): Unit = {
        ProfileAbi77.writeProfile(on, out)
        Files.writeString(out.resolve("options.txt"), options.mkString("", "\n", "\n"))
        ProfileAbi77.writeFieldOrder(on, out)
    }
}

object SharedFuture75ConfigMain extends App {
    val p = SharedFuture75Profile
    var rejected = 0
    def reject(body: => Unit): Unit = {
        var failed = false
        try { body } catch { case _: IllegalArgumentException => failed = true }
        require(failed); rejected += 1
    }
    reject { p.requireOptions(p.options.reverse) }
    reject { p.requireOptions(p.options.dropRight(1)) }
    reject { FpgaNextProfileOptions.validate(p.options :+ "--future-home-way-reservation") }
    require(p.on.copy(futureHomeWayReservation = false) == p.base.on)
    require(p.base.on.copy(sharedMemoryAddressState = false) == TimingReady73Profile.on)
    println(s"PASS_SHARED_FUTURE75_CONFIG core=177 profile=94 options=75 negative=$rejected")
}

/** Inspect the actual constructed final Home, preserving fourth-resource witnesses. */
object SharedFuture75ActualAudit {
    def capture(platform: MachinePlatform): Map[String, Any] = {
        val expected = SharedFuture75Profile.on
        val home = platform.finalHome.get.asInstanceOf[MixedCoherentLineHome]
        require(home.futureWayReservation && home.sharedLookupMatch && home.memoryScheduleOverlap)
        require(platform.core.core.core.p == expected.coreParams)
        Map("schema" -> "shared-future75-actual-v1", "sharedLookupMatch" -> home.sharedLookupMatch,
            "futureHomeWayReservation" -> home.futureWayReservation,
            "machineOptIn" -> (expected.coreParams.sharedMemoryAddressState && expected.cache.futureHomeWayReservation),
            "futureHome" -> FutureHomeActualAudit.capture(platform, expected),
            "fourthResource" -> AreaFourthResourceAudit.capture(platform), "physicalQualification" -> false)
    }
}

object SharedFuture75CpuMain extends App {
    require(args.length == 76)
    val p = SharedFuture75Profile
    p.requireOptions(args.drop(1).toSeq)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh shared-future75 CPU output required")
    p.write(out)
    var actual: Option[Map[String, Any]] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = FpgaNextBoardGsim.build(p.on, verifyConfiguration = true)
        val fields = dut.getClass.getDeclaredFields.filter(_.getType == classOf[MatchingManagedBoard])
        require(fields.length == 1)
        fields.head.setAccessible(true)
        val board = fields.head.get(dut).asInstanceOf[MatchingManagedBoard]
        actual = Some(SharedFuture75ActualAudit.capture(board.platform))
        dut
    }, Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
    ProfileAbi77.normalizeMatching(out, p.expected("fabric"), p.on)
    require(ujson.read(Files.readString(out.resolve("actual-fabric.json"))) == p.expected("fabric"))
    Files.writeString(out.resolve("actual-shared-future75.json"), PostedBoardConfiguration.json(actual.get) + "\n")
    println("PASS_SHARED_FUTURE75_ACTUAL_CPU core=177 profile=94 options=75 qualification_pending")
}
