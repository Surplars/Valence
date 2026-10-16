package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import soc.core.ooo.FpgaNextSocTop

/** Fresh CHIRRTL evidence only. Does not run FIRRTL lowering, synthesis or qualification. */
object CombinedTimingPmpR1Emission {
    def hash(bytes: Array[Byte]): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).map(b => f"${b & 255}%02x").mkString
    def arguments(args: Array[String]): (Path, Boolean) = {
        require(args.length == 2 && Set("pmp-off", "pmp-on").contains(args(1)),
            "usage: fresh-output-directory pmp-off|pmp-on")
        val out = Paths.get(args(0)).toAbsolutePath
        require(!Files.exists(out), "fresh output directory required")
        (out, args(1) == "pmp-on")
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
        Files.writeString(out.resolve("actual-combined-timing-pmp.json"), PostedBoardConfiguration.json(actual) + "\n")
        val c = CombinedTimingPmpR1Profile.config(enabled)
        Files.writeString(out.resolve("actual-core-parameters.json"), PostedBoardConfiguration.json(c.coreParams) + "\n")
        Files.writeString(out.resolve("actual-profile-parameters.json"), PostedBoardConfiguration.json(c) + "\n")
        Files.writeString(out.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(
            Map("core" -> c.coreParams.productElementNames.toSeq, "profile" -> c.productElementNames.toSeq)) + "\n")
        Files.writeString(out.resolve("emission.json"), ujson.Obj(
            "schema" -> "combined-timing-pmp-r1-chirrtl-entry-v1", "top" -> top,
            "arm" -> (if (enabled) "pmp-on" else "pmp-off"), "coreFields" -> 179, "profileFields" -> 96,
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

object CombinedTimingPmpR1NativeMain extends App {
    val (out, enabled) = CombinedTimingPmpR1Emission.arguments(args)
    var built: Option[FpgaNextSocTop] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = CombinedTimingPmpR1Profile.construct(enabled)
        built = Some(dut)
        dut
    }
    val actual = CombinedTimingPmpR1Audit.capture(built.get, CombinedTimingPmpR1Profile.config(enabled), enabled)
    CombinedTimingPmpR1Emission.write(out, "FpgaNextSocTop", fir, actual, enabled)
    println(s"PASS_COMBINED_TIMING_PMP_R1_NATIVE pmp=$enabled core=179 profile=96 ports=76 UNQUALIFIED")
}

object CombinedTimingPmpR1BoardGsimMain extends App {
    require(args.length == 3, "fresh-output-directory pmp-off|pmp-on actual-native-json required")
    val (out, enabled) = CombinedTimingPmpR1Emission.arguments(args.take(2))
    val reference = ujson.read(Files.readString(Paths.get(args(2))))
    val c = CombinedTimingPmpR1Profile.config(enabled)
    var built: Option[BoardSocGsim] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = FpgaNextBoardGsim.build(c, verifyConfiguration = true, sharedTwoWordFetchPmp = true,
            disjointEvictionStoreOverlap = true, proofBankControlDecoupling = true,
            projectedRequestHead = true, factorPreparedStorePool = true, combinedTimingR1Audit = true,
            registerNextLineDecision = enabled)
        built = Some(dut)
        dut
    }
    val actual = CombinedTimingPmpR1Audit.capturePlatform(built.get.observedPlatform, c, enabled)
    val actualJson = CombinedTimingPmpR1Audit.json(actual)
    Seq("core", "profile", "fieldOrder", "geometry", "clockHz", "featureFlags", "counts", "pmpDecisionObservation").foreach { key =>
        require(actualJson(key) == reference(key), s"GSIM/native actual mismatch: $key")
    }
    CombinedTimingPmpR1Emission.write(out, "BoardSocGsim", fir, actual, enabled)
    CombinedTimingR1FabricAudit.write(out.toString)
    Files.writeString(out.resolve("actual-combined-timing-pmp-gsim.json"), actualJson.render(indent = 2) + "\n")
    println(s"PASS_COMBINED_TIMING_PMP_R1_BOARD_CHIRRTL pmp=$enabled core=179 profile=96 UNQUALIFIED")
}

/** Exact key/value comparison; only enumerated cut changes and their actual counts are allowed. */
object CombinedTimingPmpR1CompareMain extends App {
    require(args.length == 2, "pmp-off-directory pmp-on-directory required")
    def read(dir: String): ujson.Value = ujson.read(Files.readString(Paths.get(dir, "actual-combined-timing-pmp.json")))
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
    val allowed = Set("/featureFlags/registerNextLineDecision")
    val changed = off.keySet.filter(k => off(k) != on(k))
    val widths = Set("/pmpDecisionObservation/headBits", "/pmpDecisionObservation/tailBits")
    val producers = "/pmpDecisionObservation/exportingCheckers"
    require(changed == allowed ++ widths + producers, s"unexpected actual PMP-OFF/ON differences: $changed")
    allowed.foreach(k => require(off(k) == ujson.Bool(false) && on(k) == ujson.Bool(true), k))
    widths.foreach(k => require(off(k) == ujson.Num(0) && on(k) == ujson.Num(33), k))
    require(off(producers) == ujson.Num(0) && on(producers) == ujson.Num(1))
    println("PASS_COMBINED_TIMING_PMP_R1_STRICT_DIFF REGISTERED_NEXT_LINE_DECISION_ONLY")
}
