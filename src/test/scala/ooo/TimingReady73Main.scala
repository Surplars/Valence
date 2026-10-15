package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Explicit source-pinned candidate, independent of historical profile object initializers. */
object TimingReady73Profile {
    val root = Paths.get(".").toAbsolutePath.normalize
    private val bytes = Files.readAllBytes(root.resolve("fpga/next/timing-ready73-profile.json"))
    private def sha(data: Array[Byte]): String = MessageDigest.getInstance("SHA-256").digest(data)
        .map(b => f"${b & 0xff}%02x").mkString
    require(sha(bytes) == "fc66ccb6e878d8d480c7c52ace4e512f55e06228c9995df63713c29db1e28ab7")
    val contract = ujson.read(new String(bytes, "UTF-8"))
    require(contract("schema").str == "valence-timing-ready73-profile-v1")
    private val parentBytes = Files.readAllBytes(root.resolve("fpga/next/timing-closure-profile.json"))
    require(sha(parentBytes) == contract("parent74_profile_sha256").str)
    private val parent = ujson.read(new String(parentBytes, "UTF-8"))
    private def frozenOff(v: ujson.Value): ujson.Value = v match {
        case obj: ujson.Obj => ujson.Obj.from(obj.obj.toSeq.map { case (k, x) =>
            if (k == "frozenStoreCheckedFlow") { require(x == ujson.Bool(true)); k -> ujson.Bool(false) }
            else k -> frozenOff(x)
        })
        case arr: ujson.Arr => ujson.Arr.from(arr.arr.map(frozenOff))
        case scalar => scalar
    }
    for (key <- Seq("on_profile", "on_existing_audits", "on_timing_audit", "on_fabric")) {
        require(contract(key) == frozenOff(parent(key)), "only frozen-flow may differ from full74: " + key)
    }
    require(contract("on_options").arr.map(_.str).toSeq == parent("on_options").arr.map(_.str).filterNot(_ == "--frozen-store-checked-flow").toSeq)
    val baselineBytes = Files.readAllBytes(root.resolve("fpga/next/combined-cpu-profile.json"))
    require(sha(baselineBytes) == contract("baseline_profile_sha256").str)
    private val baseline = ujson.read(new String(baselineBytes, "UTF-8"))
    val offOptions = contract("off_options").arr.map(_.str).toSeq
    val onOptions = contract("on_options").arr.map(_.str).toSeq
    require(offOptions == baseline("native_options").arr.map(_.str).toSeq && offOptions.size == 71)
    require(onOptions == offOptions ++ Seq("--registered-load-result-ready", "--tri-speed-raw-clock-handoff") && onOptions.size == 73)
    Seq(offOptions, onOptions).foreach(FpgaNextProfileOptions.validate)
    val off = FpgaNextConfig.fromOptions(offOptions.toSet, defaultSelected = false)
    val on = FpgaNextConfig.fromOptions(onOptions.toSet, defaultSelected = false)
    require(on == off.copy(registeredLoadResultReady = true, frozenStoreCheckedFlow = false,
        triSpeedRawClockHandoff = true))
    require(on.coreParams == off.coreParams.copy(registeredLoadResultReady = true, frozenStoreCheckedFlow = false))
    require(on.copy(triSpeedRawClockHandoff = false).coreParams == on.coreParams)
    require(on.cache == off.cache && on.ddr == off.ddr && on.network == off.network && on.storage == off.storage)
    require(contract("physical_options") == baseline("physical_options"), "approved native physical options changed")
    for ((side, c) <- Seq(("off", off), ("on", on))) {
        PlacedTimingProfileBridge.requireShape(c)
        ProfileAbi77.requireHistorical(c)
        require(ProfileAbi77.retained(c).size == 94 && ProfileAbi77.retained(c.coreParams).size == 177)
        require(ProfileAbi77.retainedNames(c) == contract("profile_fields").arr.map(_.str).toSeq)
        require(ProfileAbi77.retainedNames(c.coreParams) == contract("core_fields").arr.map(_.str).toSeq)
        require(document(c) == contract(side + "_profile"), "all complete typed/nested configuration values differ")
        require(c.cpuHz == 100000000 && c.issueWidth == 2 && c.coreParams.robEntries == 16 && c.coreParams.physicalRegs == 48 &&
            c.lsuEntries == 4 && c.coreParams.tagBits == 64 && c.postedYoungerLoadSealDeferral &&
            c.residentMemoryPayloadReuse && c.heldAluIssueForwarding)
    }
    // Only false named additions may be stripped, and the entire retained175/92 value document must match.
    private val retained = ujson.read(ujson.write(document(off)))
    retained("core") = ujson.read(PostedBoardConfiguration.json(
        PlacedTimingProfileBridge.priorTimingClosureFields(off.coreParams)))
    retained("profile") = ujson.read(PostedBoardConfiguration.json(
        PlacedTimingProfileBridge.priorTimingClosureFields(off)))
    require(retained == baseline("expected_profile"), "unchanged retained typed/nested values differ")
    for (c <- Seq(FpgaNextConfig(), FpgaNextConfig.Selected, FpgaNextConfig.Candidate, FpgaNextConfig.Reference)) {
        require(!c.registeredLoadResultReady && !c.frozenStoreCheckedFlow && !c.triSpeedRawClockHandoff)
        require(!c.coreParams.registeredLoadResultReady && !c.coreParams.frozenStoreCheckedFlow)
    }
    def document(c: FpgaNextConfig): ujson.Value =
        ProfileAbi77.document(c)
    def requireSide(side: String, options: Seq[String], c: FpgaNextConfig): Unit = {
        val pair = side match {
            case "off" => (offOptions, off)
            case "on" => (onOptions, on)
            case _ => throw new IllegalArgumentException("exact off/on side required")
        }
        require(options == pair._1 && c == pair._2)
        require(document(c) == contract(side + "_profile"))
    }
    def write(side: String, directory: Path): Unit = {
        val (c, options) = if (side == "off") (off, offOptions) else (on, onOptions)
        requireSide(side, options, c)
        ProfileAbi77.writeProfile(c, directory)
        Files.writeString(directory.resolve("options.txt"), options.mkString("", "\n", "\n"))
        ProfileAbi77.writeFieldOrder(c, directory)
    }
    /** Local product references are expanded before exact complete-document comparison. */
    def expected(side: String, key: String): ujson.Value = {
        require(side == "off" || side == "on")
        def expand(v: ujson.Value): ujson.Value = v match {
            case obj: ujson.Obj if obj.obj.keySet == Set("$timing_core") =>
                require(obj("$timing_core").str == side, "cross-side core reference")
                ujson.read(ujson.write(contract(side + "_profile")("core")))
            case obj: ujson.Obj => ujson.Obj.from(obj.obj.toSeq.map { case (k, x) => k -> expand(x) })
            case arr: ujson.Arr => ujson.Arr.from(arr.arr.map(expand))
            case scalar => scalar
        }
        expand(contract(side + "_" + key))
    }
    def requireActual(side: String, actual: Map[String, Any], key: String): Unit =
        require(ProfileAbi77.report(ujson.read(PostedBoardConfiguration.json(actual)), expected(side, key),
            if (key == "existing_audits") "existing" else "timing", if (side == "on") on else off) == expected(side, key),
            "complete actual constructor document differs: " + side + "/" + key)
    def requireFabric(side: String, directory: Path): Unit = {
        ProfileAbi77.normalizeMatching(directory, expected(side, "fabric"), if (side == "on") on else off)
        val actual = ujson.read(Files.readString(directory.resolve("actual-fabric.json")))
        require(actual == expected(side, "fabric"), "complete actual fabric document differs")
        require(actual("rawMediaImplementedInGsim").bool == false && actual("cdcQualified").bool == false &&
            actual("phyQualified").bool == false)
    }
}

/** Pure negative configuration tests; no hardware elaboration or simulation. */
object TimingReady73ConfigMain extends App {
    val p = TimingReady73Profile
    var rejected = 0
    def reject(body: => Unit): Unit = {
        var failed = false
        try { body } catch { case _: IllegalArgumentException => failed = true }
        require(failed, "negative control was not rejected")
        rejected += 1
    }
    reject { FpgaNextProfileOptions.validate(p.onOptions :+ "--registered-load-result-ready") }
    reject { FpgaNextProfileOptions.validate(p.onOptions :+ "--frozen-store-checked-flow=false") }
    reject { FpgaNextProfileOptions.validate(p.onOptions :+ "--unrecognized-timing-feature") }
    reject { p.requireSide("on", p.onOptions.reverse, p.on) }
    reject { p.requireSide("on", p.onOptions.dropRight(1), p.on) }
    reject { p.requireSide("on", p.onOptions, p.on.copy(triSpeedRawClockHandoff = false)) }
    reject { p.on.copy(heldAluIssueForwarding = false).coreParams; () }
    reject { p.on.copy(frozenStoreProofTransport = false).coreParams; () }
    reject { p.on.copy(robEntries = Some(32)).coreParams; () }
    reject { p.on.copy(physicalRegs = Some(64)).coreParams; () }
    reject { p.on.copy(experimentalTriSpeedEthernet = false); () }
    reject { PlacedTimingProfileBridge.priorTimingClosureFields(p.on); () }
    reject { PlacedTimingProfileBridge.priorTimingClosureFields(p.on.coreParams); () }
    reject { PlacedTimingProfileBridge.publishedFields(p.on); () }
    reject { PlacedTimingProfileBridge.historicalAFields(p.on.coreParams); () }
    println(s"PASS_TIMING_CLOSURE_CONFIG core=177 profile=94 onOptions=73 negative=$rejected")
}

/** Actual native AND matching-fabric constructors on both sides; no RTL emission. */
object TimingReady73ConstructorMain extends App {
    require(args.length == 1)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh constructor output required")
    Files.createDirectories(out)
    val p = TimingReady73Profile
    for ((side, c) <- Seq(("off", p.off), ("on", p.on))) {
        val directory = out.resolve(side)
        p.write(side, directory)
        var actual: Option[Map[String, Any]] = None
        var closure: Option[Map[String, Any]] = None
        ChiselStage.elaborate {
            val dut = new FpgaNextSocTop(c, bscanChain = 2)
            actual = Some(Map("resident" -> ResidentMemoryIntegrationActualAudit.capture(dut.board.platform, c),
                "held" -> HeldAluIntegrationActualAudit.capture(dut.board.platform, c),
                "mac" -> MacRawHandoffEntryAudit.capture(dut.board, c),
                "lvtPhysicalRegisterFile" -> dut.board.platform.core.core.core.p.lvtPhysicalRegisterFile,
                "gsimEmission" -> false, "modelBuild" -> false,
                "simulationRun" -> false, "physicalQualification" -> false))
            closure = Some(TimingClosureActualAudit.capture(dut.board.platform, c))
            dut
        }
        p.requireActual(side, actual.get, "existing_audits")
        p.requireActual(side, closure.get, "timing_audit")
        Files.writeString(directory.resolve("actual-native-constructors.json"),
            PostedBoardConfiguration.json(actual.get) + "\n")
        Files.writeString(directory.resolve("actual-timing-closure.json"),
            PostedBoardConfiguration.json(closure.get) + "\n")
        ProfileAbi77.normalizeFile(directory.resolve("actual-native-constructors.json"), p.expected(side, "existing_audits"), "existing", c)
        ProfileAbi77.normalizeFile(directory.resolve("actual-timing-closure.json"), p.expected(side, "timing_audit"), "timing", c)
        ChiselStage.elaborate { FpgaNextBoardGsim.build(c, verifyConfiguration = true) }
        val matching = directory.resolve("matching")
        Files.createDirectories(matching)
        MatchingFabricAudit.write(matching.toString)
        p.requireFabric(side, matching)
        println(s"PASS_TIMING_CLOSURE_ACTUAL side=$side core=177 profile=94 raw=${c.triSpeedRawClockHandoff}")
    }
}

/** Final native path; generic board writer and all existing audits remain active. */
object TimingReady73NativeMain extends App {
    require(args.length == 74, "fresh output and exact73 native options required")
    val p = TimingReady73Profile
    val c = FpgaNextConfig.fromOptions(args.drop(1).toSet, defaultSelected = false)
    p.requireSide("on", args.drop(1).toSeq, c)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh native output required")
    FpgaNextMain.main(args)
    ProfileAbi77.normalizeNative(out, p.contract("on_profile"), p.expected("on", "timing_audit"), p.expected("on", "existing_audits"), c)
    def read(name: String): ujson.Value = ujson.read(Files.readString(out.resolve(name)))
    require(read("profile.json") == p.contract("on_profile"))
    require(read("actual-timing-closure.json") == p.expected("on", "timing_audit"))
    for ((file, key) <- Seq(("actual-held-alu-forwarding.json", "held"),
            ("actual-resident-memory.json", "resident"), ("actual-mac-raw-handoff.json", "mac"))) {
        require(read(file) == p.expected("on", "existing_audits")(key), "native actual constructor differs: " + key)
    }
    require(read("actual-mac-raw-handoff.json")("actualHandoffPresent").bool)
    p.write("on", out)
    Files.writeString(out.resolve("timing-ready73-entry.json"), PostedBoardConfiguration.json(Map(
        "schema" -> "timing-ready73-native-actual-v1", "name" -> "combined-timing-ready-raw73-r1",
        "coreFields" -> 177, "profileFields" -> 94, "options" -> p.onOptions,
        "rawMac" -> true, "completeActualConstructorsVerified" -> true,
        "physicalQualification" -> false, "cdcQualified" -> false, "phyQualified" -> false)) + "\n")
    println("PASS_TIMING_CLOSURE_NATIVE_ACTUAL core=177 profile=94 options=73 raw=true")
}
