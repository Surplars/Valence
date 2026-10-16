package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import soc.core.ooo.FpgaNextSocTop

/** Fresh CHIRRTL evidence only. Does not run FIRRTL lowering, synthesis or qualification. */
object CombinedTimingR1Emission {
    def hash(bytes: Array[Byte]): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).map(b => f"${b & 255}%02x").mkString
    def arguments(args: Array[String]): (Path, Boolean) = {
        require(args.length == 2 && Set("baseline", "candidate").contains(args(1)),
            "usage: fresh-output-directory baseline|candidate")
        val out = Paths.get(args(0)).toAbsolutePath
        require(!Files.exists(out), "fresh output directory required")
        (out, args(1) == "candidate")
    }
    def write(out: Path, top: String, fir: String, actual: Map[String, Any], enabled: Boolean): Unit = {
        val hardware = fir.replaceAll(" @\\[[^\\n]*?\\]", "")
        val directHomeD = hardware.linesIterator.filter(l =>
            l.contains(".io.line.d") && l.contains(".io.masters[1].d")).toSeq
        require(directHomeD.size == 1, "home D must retain its direct prearbiter response connection")
        val homeLines = hardware.linesIterator.filter(_.contains("homeRequests.io")).toSeq
        if (enabled) {
            require(homeLines.exists(l => l.contains("homeRequests.io.enq") && l.contains(".io.line.a")),
                "home A must feed the new queue")
            require(homeLines.exists(l => l.contains("homeRequests.io.deq") &&
                l.contains(".io.masters[1].a")), "queue A must precede arbiter master 1")
            require(!homeLines.exists(l => l.contains(".io.line.d") || l.contains(".io.masters[1].d")),
                "home queue must not alter D response wiring")
        } else require(homeLines.isEmpty, "baseline must not instantiate home A queue")
        Files.createDirectories(out)
        Files.writeString(out.resolve(top + ".fir"), fir)
        Files.writeString(out.resolve(top + ".hardware.fir"), hardware)
        Files.writeString(out.resolve("actual-combined-timing.json"), PostedBoardConfiguration.json(actual) + "\n")
        val c = CombinedTimingR1Profile.config(enabled)
        Files.writeString(out.resolve("actual-core-parameters.json"), PostedBoardConfiguration.json(c.coreParams) + "\n")
        Files.writeString(out.resolve("actual-profile-parameters.json"), PostedBoardConfiguration.json(c) + "\n")
        Files.writeString(out.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(
            Map("core" -> c.coreParams.productElementNames.toSeq, "profile" -> c.productElementNames.toSeq)) + "\n")
        Files.writeString(out.resolve("emission.json"), ujson.Obj(
            "schema" -> "combined-timing-r1-chirrtl-entry-v1", "top" -> top,
            "arm" -> (if (enabled) "candidate" else "baseline"), "coreFields" -> 179, "profileFields" -> 96,
            "qualificationInherited" -> false, "physicalQualification" -> false,
            "chirrtlSha256" -> hash(fir.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
            "hardwareChirrtlSha256" -> hash(hardware.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
            "frozenExpectedSha256" -> hash(Files.readAllBytes(Paths.get(
                "docs/recovery/combined-timing-r1/expected-baseline.json"))),
            "prearbiterHomeQueueWiringVerified" -> true,
            "scalaVersion" -> scala.util.Properties.versionNumberString).render(indent = 2) + "\n")
    }
}

object CombinedTimingR1NativeMain extends App {
    val (out, enabled) = CombinedTimingR1Emission.arguments(args)
    var built: Option[FpgaNextSocTop] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = CombinedTimingR1Profile.construct(enabled)
        built = Some(dut)
        dut
    }
    val actual = CombinedTimingR1Audit.capture(built.get, CombinedTimingR1Profile.config(enabled), enabled)
    CombinedTimingR1Emission.write(out, "FpgaNextSocTop", fir, actual, enabled)
    println(s"PASS_COMBINED_TIMING_R1_NATIVE candidate=$enabled core=179 profile=96 ports=76 UNQUALIFIED")
}

object CombinedTimingR1BoardGsimMain extends App {
    require(args.length == 3, "fresh-output-directory baseline|candidate actual-native-json required")
    val (out, enabled) = CombinedTimingR1Emission.arguments(args.take(2))
    val reference = ujson.read(Files.readString(Paths.get(args(2))))
    val c = CombinedTimingR1Profile.config(enabled)
    var built: Option[BoardSocGsim] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = FpgaNextBoardGsim.build(c, verifyConfiguration = true, sharedTwoWordFetchPmp = true,
            disjointEvictionStoreOverlap = true, proofBankControlDecoupling = enabled,
            projectedRequestHead = enabled, factorPreparedStorePool = enabled, combinedTimingR1Audit = true)
        built = Some(dut)
        dut
    }
    val actual = CombinedTimingR1Audit.capturePlatform(built.get.observedPlatform, c, enabled)
    val actualJson = CombinedTimingR1Audit.json(actual)
    Seq("core", "profile", "fieldOrder", "geometry", "clockHz", "featureFlags", "counts").foreach { key =>
        require(actualJson(key) == reference(key), s"GSIM/native actual mismatch: $key")
    }
    CombinedTimingR1Emission.write(out, "BoardSocGsim", fir, actual, enabled)
    CombinedTimingR1FabricAudit.write(out.toString)
    Files.writeString(out.resolve("actual-combined-timing-gsim.json"), actualJson.render(indent = 2) + "\n")
    println(s"PASS_COMBINED_TIMING_R1_BOARD_CHIRRTL candidate=$enabled core=179 profile=96 UNQUALIFIED")
}

/** Exact key/value comparison; only enumerated cut changes and their actual counts are allowed. */
object CombinedTimingR1CompareMain extends App {
    require(args.length == 2, "baseline-directory candidate-directory required")
    def read(dir: String): ujson.Value = ujson.read(Files.readString(Paths.get(dir, "actual-combined-timing.json")))
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
    val booleanPaths = Set("/core/registeredHomeRequestBoundary", "/profile/registeredHomeRequestBoundary") ++
        Seq("registeredHomeRequestBoundary", "projectedRequestHead", "factorPreparedStorePool",
            "proofBankControlDecoupling", "shadowEarlyProofBind", "proofBankQuiesceIntent",
            "proofOwnerStateCleanup", "proofCheckBindPlanning", "latePoolEnable", "directSelectedRank").map("/featureFlags/" + _)
    val countPaths = Set("/counts/projectedHeadQueues", "/counts/homeRequestQueues")
    val changed = off.keySet.filter(k => off(k) != on(k))
    require(changed == booleanPaths ++ countPaths, s"unexpected actual OFF/ON differences: $changed")
    booleanPaths.foreach(k => require(off(k) == ujson.Bool(false) && on(k) == ujson.Bool(true), k))
    countPaths.foreach(k => require(off(k) == ujson.Num(0) && on(k) == ujson.Num(1), k))
    println("PASS_COMBINED_TIMING_R1_STRICT_DIFF home+projected-head+prepared-pool+proof-control ONLY")
}
