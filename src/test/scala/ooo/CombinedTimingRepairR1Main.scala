package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import soc.core.ooo.FpgaNextSocTop

/** Fresh CHIRRTL evidence only. Does not run FIRRTL lowering, synthesis or qualification. */
object CombinedTimingRepairR1Emission {
    def hash(bytes: Array[Byte]): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).map(b => f"${b & 255}%02x").mkString
    def arguments(args: Array[String]): (Path, Boolean) = {
        require(args.length == 2 && Set("repair-off", "repair-on").contains(args(1)),
            "usage: fresh-output-directory repair-off|repair-on")
        val out = Paths.get(args(0)).toAbsolutePath
        require(!Files.exists(out), "fresh output directory required")
        (out, args(1) == "repair-on")
    }
    def write(out: Path, top: String, fir: String, actual: Map[String, Any], enabled: Boolean): Unit = {
        val hardware = fir.replaceAll(" @\\[[^\\n]*?\\]", "")
        val directHomeD = hardware.linesIterator.filter(l =>
            l.contains(".io.line.d") && l.contains(".io.masters[1].d")).toSeq
        require(directHomeD.size == 1, "home D must retain its direct prearbiter response connection")
        val homeLines = hardware.linesIterator.filter(_.contains("homeRequests.io")).toSeq
        locally {
            require(homeLines.exists(l => l.contains("homeRequests.io.enq") && l.contains(".io.line.a")),
                "home A must feed the new queue")
            require(homeLines.exists(l => l.contains("homeRequests.io.deq") &&
                l.contains(".io.masters[1].a")), "queue A must precede arbiter master 1")
            require(!homeLines.exists(l => l.contains(".io.line.d") || l.contains(".io.masters[1].d")),
                "home queue must not alter D response wiring")
        }
        Files.createDirectories(out)
        Files.writeString(out.resolve(top + ".fir"), fir)
        Files.writeString(out.resolve(top + ".hardware.fir"), hardware)
        Files.writeString(out.resolve("actual-combined-timing-repair.json"), PostedBoardConfiguration.json(actual) + "\n")
        val c = CombinedTimingRepairR1Profile.config(enabled)
        Files.writeString(out.resolve("actual-core-parameters.json"), PostedBoardConfiguration.json(c.coreParams) + "\n")
        Files.writeString(out.resolve("actual-profile-parameters.json"), PostedBoardConfiguration.json(c) + "\n")
        Files.writeString(out.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(
            Map("core" -> c.coreParams.productElementNames.toSeq, "profile" -> c.productElementNames.toSeq)) + "\n")
        Files.writeString(out.resolve("emission.json"), ujson.Obj(
            "schema" -> "combined-timing-repair-r1-chirrtl-entry-v1", "top" -> top,
            "arm" -> (if (enabled) "repair-on" else "repair-off"), "coreFields" -> 179, "profileFields" -> 96,
            "qualificationInherited" -> false, "physicalQualification" -> false,
            "chirrtlSha256" -> hash(fir.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
            "hardwareChirrtlSha256" -> hash(hardware.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
            "frozenExpectedSha256" -> hash(Files.readAllBytes(Paths.get(
                "docs/recovery/combined-timing-pmp-r1/expected-full-c1.json"))),
            "frozenPmpOffNativeExpectedSha256" -> hash(Files.readAllBytes(Paths.get(
                "docs/recovery/combined-timing-pmp-r1/expected-pmp-off-native.json"))),
            "prearbiterHomeQueueWiringVerified" -> true,
            "scalaVersion" -> scala.util.Properties.versionNumberString).render(indent = 2) + "\n")
    }
}

object CombinedTimingRepairR1NativeMain extends App {
    val (out, enabled) = CombinedTimingRepairR1Emission.arguments(args)
    var built: Option[FpgaNextSocTop] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = CombinedTimingRepairR1Profile.construct(enabled)
        built = Some(dut)
        dut
    }
    val actual = CombinedTimingRepairR1Audit.capture(built.get, CombinedTimingRepairR1Profile.config(enabled), enabled)
    CombinedTimingRepairR1Emission.write(out, "FpgaNextSocTop", fir, actual, enabled)
    println(s"PASS_COMBINED_TIMING_REPAIR_R1_NATIVE pmp=$enabled core=179 profile=96 ports=76 UNQUALIFIED")
}

object CombinedTimingRepairR1BoardGsimMain extends App {
    require(args.length == 3, "fresh-output-directory repair-off|repair-on actual-native-json required")
    val (out, enabled) = CombinedTimingRepairR1Emission.arguments(args.take(2))
    val reference = ujson.read(Files.readString(Paths.get(args(2))))
    require(reference("schema") == ujson.Str("combined-timing-repair-r1-native-actual-v1") &&
        reference("topPorts").arr.size == 76, "GSIM reference must be actual native evidence")
    val c = CombinedTimingRepairR1Profile.config(enabled)
    var built: Option[BoardSocGsim] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = FpgaNextBoardGsim.build(c, verifyConfiguration = true, sharedTwoWordFetchPmp = true,
            disjointEvictionStoreOverlap = true, proofBankControlDecoupling = true,
            projectedRequestHead = true, factorPreparedStorePool = true, combinedTimingR1Audit = true,
            registerNextLineDecision = enabled,
            registeredMemoryPreparationDescriptor = enabled, backendNaturalAlignedPmp = enabled)
        built = Some(dut)
        dut
    }
    val actual = CombinedTimingRepairR1Audit.capturePlatform(built.get.observedPlatform, c, enabled)
    val actualJson = CombinedTimingRepairR1Audit.json(actual)
    Seq("core", "profile", "fieldOrder", "geometry", "clockHz", "featureFlags", "counts", "pmpDecisionObservation", "descriptorObservation").foreach { key =>
        require(actualJson(key) == reference(key), s"GSIM/native actual mismatch: $key")
    }
    CombinedTimingRepairR1Emission.write(out, "BoardSocGsim", fir, actual, enabled)
    if (enabled) CombinedTimingRepairR1FabricAudit.write(out.toString)
    else CombinedTimingR1FabricAudit.write(out.toString)
    Files.writeString(out.resolve("actual-combined-timing-repair-gsim.json"), actualJson.render(indent = 2) + "\n")
    println(s"PASS_COMBINED_TIMING_REPAIR_R1_BOARD_CHIRRTL pmp=$enabled core=179 profile=96 UNQUALIFIED")
}

/** Exact key/value comparison; only enumerated cut changes and their actual counts are allowed. */
object CombinedTimingRepairR1CompareMain extends App {
    require(args.length == 2, "repair-off-directory repair-on-directory required")
    def read(dir: String): ujson.Value = {
        val value = ujson.read(Files.readString(Paths.get(dir, "actual-combined-timing-repair.json")))
        require(value("schema") == ujson.Str("combined-timing-repair-r1-native-actual-v1") &&
            value("topPorts").arr.size == 76, "comparison requires actual native evidence")
        value
    }
    def flatten(v: ujson.Value, path: String = ""): Map[String, ujson.Value] = v match {
        case obj: ujson.Obj => Map(path -> ujson.Str("object")) ++
            obj.value.toSeq.flatMap { case (k, x) => flatten(x, path + "/" + k) }.toMap
        case arr: ujson.Arr => Map(path -> ujson.Str("array")) ++
            arr.value.zipWithIndex.flatMap { case (x, i) => flatten(x, path + "/" + i) }.toMap
        case leaf => Map(path -> leaf)
    }
    val off = flatten(read(args(0)))
    val on = flatten(read(args(1)))
    require(off.keySet == on.keySet, "audit schema/key set changed")
    val allowed = Set("/featureFlags/registerNextLineDecision", "/featureFlags/registeredMemoryPreparationDescriptor", "/featureFlags/backendNaturalAlignedPmp")
    val changed = off.keySet.filter(k => off(k) != on(k))
    val widths = Set("/pmpDecisionObservation/headBits", "/pmpDecisionObservation/tailBits")
    val producers = "/pmpDecisionObservation/exportingCheckers"
    val descriptorBits = Set("/descriptorObservation/payloadBits", "/descriptorObservation/validBits")
    val selectorCounts = Set("/counts/residentSelectors", "/counts/descriptorSelectors")
    val absentSelectorFlags = Set("/featureFlags/latePoolEnable", "/featureFlags/directSelectedRank", "/featureFlags/rankResidentPriority")
    require(changed == allowed ++ widths ++ descriptorBits ++ selectorCounts ++ absentSelectorFlags + producers,
        s"unexpected actual repair-OFF/ON differences: $changed")
    require(off("/descriptorObservation/payloadBits") == ujson.Num(0) && on("/descriptorObservation/payloadBits") == ujson.Num(275))
    require(off("/descriptorObservation/validBits") == ujson.Num(0) && on("/descriptorObservation/validBits") == ujson.Num(1))
    require(off("/counts/residentSelectors") == ujson.Num(1) && on("/counts/residentSelectors") == ujson.Num(0))
    require(off("/counts/descriptorSelectors") == ujson.Num(0) && on("/counts/descriptorSelectors") == ujson.Num(1))
    absentSelectorFlags.foreach(k => require(off(k) == ujson.Bool(true) && on(k) == ujson.Null, k))
    allowed.foreach(k => require(off(k) == ujson.Bool(false) && on(k) == ujson.Bool(true), k))
    widths.foreach(k => require(off(k) == ujson.Num(0) && on(k) == ujson.Num(33), k))
    require(off(producers) == ujson.Num(0) && on(producers) == ujson.Num(1))
    println("PASS_COMBINED_TIMING_REPAIR_R1_STRICT_DIFF PMP_DESCRIPTOR_ALIGNED_BACKEND_ONLY")
}
