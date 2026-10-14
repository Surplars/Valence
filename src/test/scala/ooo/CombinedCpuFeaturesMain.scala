package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Strict, separate combination entry. No production or historical bridge changes. */
object CombinedCpuFeaturesProfile {
    val off = ResidentMemoryIntegrationProfile.on
    val offOptions = ResidentMemoryIntegrationProfile.onOptions
    val onOptions = offOptions :+ "--held-alu-issue-forwarding"
    val on = FpgaNextConfig.fromOptions(onOptions.toSet, defaultSelected = false)
    require(offOptions.size == 70 && onOptions.size == 71 && onOptions.distinct.size == 71)
    Seq(offOptions, onOptions).foreach(FpgaNextProfileOptions.validate)
    require(on == off.copy(heldAluIssueForwarding = true))
    require(on.coreParams == off.coreParams.copy(heldAluIssueForwarding = true))
    for (c <- Seq(off, on)) {
        PlacedTimingProfileBridge.requireShape(c)
        require(c.productArity == 92 && c.coreParams.productArity == 175)
        require(c.productElementNames.toSeq == ResidentMemoryIntegrationProfile.currentProfileNames)
        require(c.coreParams.productElementNames.toSeq == ResidentMemoryIntegrationProfile.currentCoreNames)
        require(c.postedYoungerLoadSealDeferral && c.residentMemoryPayloadReuse && !c.triSpeedRawClockHandoff)
        require(c.cpuHz == 100000000 && c.issueWidth == 2)
        val p = c.coreParams
        require(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 &&
            p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
    }
    require(!off.heldAluIssueForwarding && on.heldAluIssueForwarding)
    private val namedProfilePath = NearTermAProfile.root.resolve("fpga/next/combined-cpu-profile.json")
    private val namedBytes = Files.readAllBytes(namedProfilePath)
    private val namedHash = MessageDigest.getInstance("SHA-256").digest(namedBytes)
        .map(b => f"${b & 0xff}%02x").mkString
    require(namedHash == "5f515773787a45a6fba0854a0bdf040938b0caba7322ff90bc179de5661226ab", "strict combined profile source changed")
    val namedProfile = ujson.read(new String(namedBytes, "UTF-8"))
    require(namedProfile("schema").str == "valence-combined-cpu-native-entry-v1")
    require(namedProfile("native_options").arr.map(_.str).toSeq == onOptions)
    require(ujson.read(PostedBoardConfiguration.json(PostedBoardConfiguration.document(on))) ==
        namedProfile("expected_profile"), "complete combined 175/92 typed/nested product differs")
    require(namedProfile("core_fields").arr.map(_.str).toSeq == on.coreParams.productElementNames.toSeq)
    require(namedProfile("profile_fields").arr.map(_.str).toSeq == on.productElementNames.toSeq)
    // Both true-feature candidates must still be rejected by the historical false-only projection.
    for (c <- Seq(off, on)) {
        var rejected = false
        try { ResidentMemoryIntegrationProfile.historicalDocument(c) }
        catch { case _: IllegalArgumentException => rejected = true }
        require(rejected, "historical projection must never erase a true resident or held feature")
    }
    def expectedConstructor(c: FpgaNextConfig): ujson.Value = {
        require(c == off || c == on)
        val result = ujson.read(ujson.write(namedProfile("expected_constructor")))
        // Exact current OFF/ON pair, never a historical true-field projection.
        for (kind <- Seq("resident", "held"); leaf <- Seq("core", "backend", "ledger")) {
            result(kind)(leaf)("heldAluIssueForwarding") = ujson.Bool(c.heldAluIssueForwarding)
        }
        result("held")("heldAluIssueForwarding") = ujson.Bool(c.heldAluIssueForwarding)
        result
    }
    def requireSide(side: String, options: Seq[String], c: FpgaNextConfig): Unit = {
        val expected = side match {
            case "off" => (offOptions, off)
            case "on" => (onOptions, on)
            case _ => throw new IllegalArgumentException("exact off/on required")
        }
        require(options == expected._1 && c == expected._2)
    }
    def write(c: FpgaNextConfig, options: Seq[String], directory: String): Unit = {
        require(c == off || c == on)
        PostedBoardConfiguration.write(c, directory)
        val out = Paths.get(directory)
        Files.writeString(out.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(Map(
            "core" -> c.coreParams.productElementNames.toSeq,
            "profile" -> c.productElementNames.toSeq)) + "\n")
        Files.writeString(out.resolve("options.txt"), options.mkString("", "\n", "\n"))
    }
}

object CombinedCpuFeaturesConstructorMain extends App {
    require(args.length == 1)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh actual constructor output required")
    Files.createDirectories(out)
    val profile = CombinedCpuFeaturesProfile
    for ((label, c, options) <- Seq(("off", profile.off, profile.offOptions),
            ("on", profile.on, profile.onOptions))) {
        profile.requireSide(label, options, c)
        var observed: Option[Map[String, Any]] = None
        ChiselStage.elaborate {
            val dut = new FpgaNextSocTop(c, bscanChain = 2)
            val resident = ResidentMemoryIntegrationActualAudit.capture(dut.board.platform, c)
            val held = HeldAluIntegrationActualAudit.capture(dut.board.platform, c)
            val mac = MacRawHandoffEntryAudit.capture(dut.board, c)
            require(dut.board.platform.core.core.core.p.lvtPhysicalRegisterFile)
            observed = Some(Map("resident" -> resident, "held" -> held, "mac" -> mac,
                "lvtPhysicalRegisterFile" -> true, "gsimEmission" -> false,
                "modelBuild" -> false, "simulationRun" -> false, "physicalQualification" -> false))
            dut
        }
        require(observed.isDefined)
        require(ujson.read(PostedBoardConfiguration.json(observed.get)) == profile.expectedConstructor(c),
            "complete actual native OFF/ON constructor differs from the strict paired expectation")
        val side = out.resolve(label)
        profile.write(c, options, side.toString)
        Files.writeString(side.resolve("actual-constructor.json"),
            PostedBoardConfiguration.json(observed.get) + "\n")
        println(s"PASS_COMBINED_ACTUAL_CONSTRUCTOR side=$label core=175 profile=92 young=true resident=true held=${c.heldAluIssueForwarding} raw=false")
    }
}

object CombinedCpuFeaturesFullCpuMain extends App {
    require(args.length == 72, "fresh directory and exact 71 options required")
    val options = args.drop(1).toSeq
    val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    CombinedCpuFeaturesProfile.requireSide("on", options, c)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh sole ON emission required")
    CombinedCpuFeaturesProfile.write(c, options, out.toString)
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true),
        Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
}

/** Explicit native export only. The generic native writer retains every existing audit and wrapper. */
object CombinedCpuFeaturesNativeMain extends App {
    require(args.length == 72, "fresh directory and exact 71 combined native options required")
    val options = args.drop(1).toSeq
    val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    CombinedCpuFeaturesProfile.requireSide("on", options, c)
    val output = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(output), "fresh combined native output required")
    FpgaNextMain.main(args)
    def document(name: String): ujson.Value = ujson.read(Files.readString(output.resolve(name)))
    val expected = CombinedCpuFeaturesProfile.namedProfile
    require(document("profile.json") == expected("expected_profile"),
        "actual native complete combined profile differs")
    for ((filename, key) <- Seq(("actual-held-alu-forwarding.json", "held"),
            ("actual-resident-memory.json", "resident"), ("actual-mac-raw-handoff.json", "mac"))) {
        require(document(filename) == expected("expected_constructor")(key),
            "actual native complete constructor differs: " + key)
    }
    Files.writeString(output.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(Map(
        "core" -> c.coreParams.productElementNames.toSeq, "profile" -> c.productElementNames.toSeq)) + "\n")
    Files.writeString(output.resolve("combined-cpu-entry.json"), PostedBoardConfiguration.json(Map(
        "schema" -> "combined-cpu-native-actual-v1", "name" -> "combined-young-resident-held-r1",
        "options" -> options, "coreFields" -> 175, "profileFields" -> 92,
        "young" -> true, "resident" -> true, "held" -> true, "rawMac" -> false,
        "completeActualConstructorsVerified" -> true, "physicalQualification" -> false)) + "\n")
    println("PASS_COMBINED_NATIVE_ACTUAL core=175 profile=92 young=true resident=true held=true raw=false")
}
