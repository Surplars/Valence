package ooo

import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Explicit live ABI and false-only historical views; never changes hardware parameters. */
object ProfileAbi77 {
    private val frozenBytes = Files.readAllBytes(Paths.get("fpga/next/shared-lru76-profile.json"))
    require(MessageDigest.getInstance("SHA-256").digest(frozenBytes).map(b => f"${b & 0xff}%02x").mkString ==
        "1a6748ca96aadd0bf77a4484a6eab1e981619414b326b0f0c8826a8059d2b8f5", "frozen76 profile changed")
    private val frozen = ujson.read(new String(frozenBytes, java.nio.charset.StandardCharsets.UTF_8))
    val field = "pendingReadyStoreQuery"
    val coreNames76 = frozen("core_fields").arr.map(_.str).toSeq
    val profileNames76 = frozen("profile_fields").arr.map(_.str).toSeq
    val coreNames = coreNames76 :+ field
    val profileNames = profileNames76 :+ field
    require(coreNames76.size == 177 && profileNames76.size == 94)
    require(coreNames.distinct == coreNames && profileNames.distinct == profileNames)
    private def names(kind: String, current: Boolean): Seq[String] = (kind, current) match {
        case ("core", true) => coreNames
        case ("core", false) => coreNames76
        case ("profile", true) => profileNames
        case ("profile", false) => profileNames76
        case _ => throw new IllegalArgumentException("unknown exact product kind")
    }
    private def kind(p: Product): String = p match {
        case _: OooParams => "core"
        case _: FpgaNextConfig => "profile"
        case _ => throw new IllegalArgumentException("only complete live core/profile products")
    }
    def requireLive(p: Product): Unit = {
        val k = kind(p)
        require(p.productElementNames.toSeq == names(k, true), "live names/order changed")
        require(p.productArity == names(k, true).size, "live arity changed")
        val reference: Product = if (k == "core") OooParams() else FpgaNextConfig()
        require(p.productIterator.zip(reference.productIterator).forall {
            case (a: Option[_], b: Option[_]) => a.forall(_.isInstanceOf[Int]) && b.forall(_.isInstanceOf[Int])
            case (a, b) => a != null && b != null && a.getClass == b.getClass
        }, "live product value types changed")
    }
    def requireLive(c: FpgaNextConfig): Unit = {
        requireLive(c: Product); requireLive(c.coreParams: Product)
        require(!FpgaNextConfig().pendingReadyStoreQuery && !OooParams().pendingReadyStoreQuery)
        require(c.pendingReadyStoreQuery == c.coreParams.pendingReadyStoreQuery, "query forwarding differs")
    }
    def requireHistorical(c: FpgaNextConfig): Unit = {
        requireLive(c)
        require(!c.pendingReadyStoreQuery && !c.coreParams.pendingReadyStoreQuery,
            "historical projection cannot drop an enabled query77 switch")
    }
    /** Exposed to focused negative tests; all production callers pass a checked Product. */
    private[ooo] def retainedEntries(entries: Seq[(String, Any)], k: String): Seq[(String, Any)] = {
        require(entries.map(_._1) == names(k, true), "exact complete names/order required")
        val reference: Product = if (k == "core") OooParams() else FpgaNextConfig()
        require(entries.map(_._2).zip(reference.productIterator.toSeq).forall {
            case (a: Option[_], b: Option[_]) => a.forall(_.isInstanceOf[Int]) && b.forall(_.isInstanceOf[Int])
            case (a, b) => a != null && b != null && a.getClass == b.getClass
        }, "complete entry types changed")
        require(entries.last._1 == field && entries.last._2 == false && entries.last._2.isInstanceOf[Boolean],
            "only a literal false query77 switch may be removed")
        entries.dropRight(1)
    }
    def retained(p: Product): Map[String, Any] = {
        requireLive(p)
        retainedEntries(p.productElementNames.zip(p.productIterator).toSeq, kind(p)).toMap
    }
    def retainedNames(p: Product): Seq[String] = {
        retained(p); names(kind(p), false)
    }
    def document(c: FpgaNextConfig): ujson.Value = {
        requireHistorical(c)
        val live = ujson.read(PostedBoardConfiguration.json(PostedBoardConfiguration.document(c)))
        live("profile") = ujson.read(PostedBoardConfiguration.json(retained(c)))
        live("core") = ujson.read(PostedBoardConfiguration.json(retained(c.coreParams)))
        live
    }
    // Explicit product/name/count locations for the frozen73-76 report schemas.
    // Never infer a projection from a matching key name or integer value alone.
    private val layouts = ujson.read("""{"profile":{"product_paths":{"/core":"core","/profile":"profile"},"metadata_paths":{}},"core":{"product_paths":{"":"core"},"metadata_paths":{}},"field-order":{"product_paths":{},"metadata_paths":{"/core":"core-names","/profile":"profile-names"}},"fabric":{"product_paths":{"/cpu":"core","/heldAluIssueForwarding/backend":"core","/heldAluIssueForwarding/core":"core","/heldAluIssueForwarding/ledger":"core","/residentMemoryPayloadReuse/backend":"core","/residentMemoryPayloadReuse/core":"core","/residentMemoryPayloadReuse/ledger":"core","/timingClosure/core":"core","/timingClosure/backend":"core","/timingClosure/ledger":"core","/timingClosure/lsu":"core","/timingClosure/lsuSlots/0":"core","/timingClosure/lsuSlots/1":"core","/timingClosure/lsuSlots/2":"core","/timingClosure/lsuSlots/3":"core","/timingClosure/ownerReady":"core","/timingClosure/allocationReady/0":"core","/timingClosure/translation":"core"},"metadata_paths":{"/headDrain/coreFields":"core-count","/headDrain/profileFields":"profile-count","/heldAluIssueForwarding/coreFields":"core-count","/heldAluIssueForwarding/coreNames":"core-names","/heldAluIssueForwarding/nearTermA/coreFields":"core-count","/heldAluIssueForwarding/nearTermA/profileFields":"profile-count","/heldAluIssueForwarding/profileFields":"profile-count","/heldAluIssueForwarding/profileNames":"profile-names","/memoryPreparationLocality/coreFields":"core-count","/nearTermA/coreFields":"core-count","/nearTermA/profileFields":"profile-count","/placedTiming/headDrain/coreFields":"core-count","/placedTiming/headDrain/profileFields":"profile-count","/placedTiming/memoryPreparationLocality/coreFields":"core-count","/placedTiming/nearTermA/coreFields":"core-count","/placedTiming/nearTermA/profileFields":"profile-count","/placedTiming/retirementIntent/coreFields":"core-count","/placedTiming/retirementIntent/profileFields":"profile-count","/residentMemoryPayloadReuse/coreFields":"core-count","/residentMemoryPayloadReuse/coreNames":"core-names","/residentMemoryPayloadReuse/profileFields":"profile-count","/residentMemoryPayloadReuse/profileNames":"profile-names","/retirementIntent/coreFields":"core-count","/retirementIntent/profileFields":"profile-count","/timingStages/coreFields":"core-count","/timingStages/profileFields":"profile-count","/timingClosure/coreFields":"core-count","/timingClosure/profileFields":"profile-count"}},"timing":{"product_paths":{"/core":"core","/backend":"core","/ledger":"core","/lsu":"core","/lsuSlots/0":"core","/lsuSlots/1":"core","/lsuSlots/2":"core","/lsuSlots/3":"core","/ownerReady":"core","/allocationReady/0":"core","/translation":"core"},"metadata_paths":{"/coreFields":"core-count","/profileFields":"profile-count"}},"existing":{"product_paths":{"/held/backend":"core","/held/core":"core","/held/ledger":"core","/resident/backend":"core","/resident/core":"core","/resident/ledger":"core"},"metadata_paths":{"/held/coreFields":"core-count","/held/coreNames":"core-names","/held/nearTermA/coreFields":"core-count","/held/nearTermA/profileFields":"profile-count","/held/profileFields":"profile-count","/held/profileNames":"profile-names","/mac/coreFields":"core-count","/mac/profileFields":"profile-count","/resident/coreFields":"core-count","/resident/coreNames":"core-names","/resident/profileFields":"profile-count","/resident/profileNames":"profile-names"}},"held":{"product_paths":{"/backend":"core","/core":"core","/ledger":"core"},"metadata_paths":{"/coreFields":"core-count","/coreNames":"core-names","/nearTermA/coreFields":"core-count","/nearTermA/profileFields":"profile-count","/profileFields":"profile-count","/profileNames":"profile-names"}},"resident":{"product_paths":{"/backend":"core","/core":"core","/ledger":"core"},"metadata_paths":{"/coreFields":"core-count","/coreNames":"core-names","/profileFields":"profile-count","/profileNames":"profile-names"}},"mac":{"product_paths":{},"metadata_paths":{"/coreFields":"core-count","/profileFields":"profile-count"}}}""")
    def report(actual: ujson.Value, expected: ujson.Value, view: String, c: FpgaNextConfig): ujson.Value = {
        requireHistorical(c)
        require(layouts.obj.contains(view), "unknown historical report schema")
        val layout = layouts(view)
        val products = layout("product_paths").obj.toMap
        val metadata = layout("metadata_paths").obj.toMap
        val visited = scala.collection.mutable.Set[String]()
        def walk(a: ujson.Value, e: ujson.Value, path: String): ujson.Value = {
            if (products.contains(path)) {
                visited += path
                val k = products(path).str
                require(e.obj.keySet == names(k, false).toSet && a.obj.keySet == names(k, true).toSet,
                    "historical/live product key set differs at " + path)
                require(a(field) == ujson.Bool(false), "enabled or mistyped query at " + path)
                ujson.Obj.from(names(k, false).map(n => n -> a(n)))
            } else if (metadata.contains(path)) {
                visited += path
                val item = metadata(path).str
                val k = if (item.startsWith("core-")) "core" else "profile"
                if (item.endsWith("-count")) {
                    require(a == ujson.Num(names(k, true).size) && e == ujson.Num(names(k, false).size),
                        "exact live/historical count differs at " + path)
                    ujson.Num(names(k, false).size)
                } else {
                    require(a == ujson.Arr.from(names(k, true)) && e == ujson.Arr.from(names(k, false)),
                        "exact live/historical ordered names differ at " + path)
                    ujson.Arr.from(names(k, false))
                }
            } else (a, e) match {
                case (aa: ujson.Obj, ee: ujson.Obj) =>
                    require(aa.obj.keySet == ee.obj.keySet, "unknown/missing report key at " + path)
                    ujson.Obj.from(ee.obj.toSeq.map { case (n, value) => n -> walk(aa(n), value, path + "/" + n) })
                case (aa: ujson.Arr, ee: ujson.Arr) =>
                    require(aa.arr.size == ee.arr.size, "report array size differs at " + path)
                    ujson.Arr.from(aa.arr.zip(ee.arr).zipWithIndex.map { case ((x, y), i) => walk(x, y, path + "/" + i) })
                case _ => a
            }
        }
        val projected = walk(actual, expected, "")
        require(visited.toSet == products.keySet ++ metadata.keySet, "declared projection path absent")
        require(projected == expected, "complete retained report values differ: " + view)
        projected
    }
    def normalizeFile(path: Path, expected: ujson.Value, view: String, c: FpgaNextConfig): Unit = {
        val raw = Files.readString(path)
        val live = ujson.read(raw)
        val projected = report(live, expected, view, c)
        val saved = path.resolveSibling(path.getFileName.toString.stripSuffix(".json") + ".live77.json")
        if (Files.exists(saved)) require(Files.readString(saved) == raw, "live witness changed")
        else Files.writeString(saved, raw)
        Files.writeString(path, projected.render(indent = 2) + "\n")
    }
    def writeProfile(c: FpgaNextConfig, out: Path): Unit = {
        requireHistorical(c)
        PostedBoardConfiguration.write(c, out.toString)
        normalizeFile(out.resolve("profile.json"), document(c), "profile", c)
    }
    def writeFieldOrder(c: FpgaNextConfig, out: Path): Unit = {
        requireHistorical(c)
        val live = ujson.Obj("core" -> ujson.Arr.from(coreNames), "profile" -> ujson.Arr.from(profileNames))
        val expected = ujson.Obj("core" -> ujson.Arr.from(coreNames76), "profile" -> ujson.Arr.from(profileNames76))
        val file = out.resolve("actual-product-field-order.json")
        Files.writeString(file, live.render(indent = 2) + "\n")
        normalizeFile(file, expected, "field-order", c)
    }
    def normalizeMatching(out: Path, fabric: ujson.Value, c: FpgaNextConfig): Unit = {
        normalizeFile(out.resolve("actual-fabric.json"), fabric, "fabric", c)
        normalizeFile(out.resolve("actual-core-parameters.json"), fabric("cpu"), "core", c)
        normalizeFile(out.resolve("actual-timing-closure.json"), fabric("timingClosure"), "timing", c)
        normalizeFile(out.resolve("actual-resident-memory.json"), fabric("residentMemoryPayloadReuse"), "resident", c)
    }
    def normalizeNative(out: Path, profile: ujson.Value, timing: ujson.Value,
            existing: ujson.Value, c: FpgaNextConfig): Unit = {
        normalizeFile(out.resolve("profile.json"), profile, "profile", c)
        normalizeFile(out.resolve("actual-timing-closure.json"), timing, "timing", c)
        for ((file, view) <- Seq("actual-held-alu-forwarding.json" -> "held",
                "actual-resident-memory.json" -> "resident", "actual-mac-raw-handoff.json" -> "mac"))
            normalizeFile(out.resolve(file), existing(view), view, c)
    }

}
