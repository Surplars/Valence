package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Separate candidate: historical exact73 bytes and qualification remain unchanged. */
object AreaFourthResourceProfile {
    val base = TimingReady73Profile
    val contract = ujson.read(Files.readString(Paths.get("fpga/next/area-fourth-resource74-profile.json")))
    require(contract("schema").str == "valence-area-fourth-resource74-v1")
    private val parentBytes = Files.readAllBytes(Paths.get("fpga/next/timing-ready73-profile.json"))
    require(MessageDigest.getInstance("SHA-256").digest(parentBytes).map(b => f"${b & 0xff}%02x").mkString ==
        contract("parent73_sha256").str)
    val options = base.onOptions :+ "--shared-memory-address-state"
    require(options.size == 74 && options == contract("on_options").arr.map(_.str).toSeq)
    FpgaNextProfileOptions.validate(options)
    val on = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    require(on == base.on.copy(sharedMemoryAddressState = true))
    require(on.coreParams == base.on.coreParams.copy(sharedMemoryAddressState = true))
    require(on.storage == base.on.storage.copy(sharedMemoryAddressState = true))
    require(on.productArity == 94 && on.coreParams.productArity == 177)
    require(on.productElementNames.toSeq == base.on.productElementNames.toSeq &&
        on.coreParams.productElementNames.toSeq == base.on.coreParams.productElementNames.toSeq)
    require(on.productElementNames.toSeq == contract("profile_fields").arr.map(_.str).toSeq &&
        on.coreParams.productElementNames.toSeq == contract("core_fields").arr.map(_.str).toSeq)
    require(on.cache == base.on.cache && on.ddr == base.on.ddr && on.network == base.on.network)
    require(contract("physical_options") == base.contract("physical_options"))
    require(on.issueWidth == 2 && on.coreParams.robEntries == 16 && on.coreParams.physicalRegs == 48 &&
        on.coreParams.tagBits == 64 && on.coreParams.registeredMulDivOperands)
    def transform(v: ujson.Value): ujson.Value = v match {
        case obj: ujson.Obj => ujson.Obj.from(obj.obj.toSeq.map { case (k, x) =>
            if (k == "sharedMemoryAddressState") { require(x == ujson.Bool(false)); k -> ujson.Bool(true) }
            else k -> transform(x)
        })
        case arr: ujson.Arr => ujson.Arr.from(arr.arr.map(transform))
        case scalar => scalar
    }
    for (key <- Seq("on_profile", "on_existing_audits", "on_timing_audit", "on_fabric"))
        require(contract(key) == transform(base.contract(key)), "unapproved candidate contract change: " + key)
    require(base.document(on) == contract("on_profile"))
    def expected(key: String): ujson.Value = transform(base.expected("on", key))
    def requireOptions(actual: Seq[String]): Unit = require(actual == options)
    def write(out: Path): Unit = {
        PostedBoardConfiguration.write(on, out.toString)
        Files.writeString(out.resolve("options.txt"), options.mkString("", "\n", "\n"))
        Files.writeString(out.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(Map(
            "core" -> on.coreParams.productElementNames.toSeq, "profile" -> on.productElementNames.toSeq)) + "\n")
    }
    def requireFabric(out: Path): Unit =
        require(ujson.read(Files.readString(out.resolve("actual-fabric.json"))) == expected("fabric"))
}

/** New constructor witnesses only, with no DUT observation ports or state. */
object AreaFourthResourceAudit {
    def capture(platform: MachinePlatform): Map[String, Any] = {
        val p = AreaFourthResourceProfile.on.coreParams
        val backend = platform.core.core.core.backend
        require(backend.p == p && backend.ledger.p == p && p.sharedMemoryAddressState)
        require(backend.multiplier.tags.isEmpty, "bounded multiplier path not enabled")
        require(backend.sharedAddressLoadWrite.nonEmpty && backend.sharedAddressStoreWrites.nonEmpty)
        require(backend.loadLanes eq backend.storeByteLanes)
        require(backend.storeAddress.size == 16 && backend.storeAddress.forall(_.getWidth == 64))
        Map("schema" -> "fourth-resource-actual-v1", "core" -> p,
            "boundedMultiplierTagsAbsent" -> backend.multiplier.tags.isEmpty,
            "sharedAddressLoadWritePresent" -> backend.sharedAddressLoadWrite.nonEmpty,
            "sharedAddressStoreWritesPresent" -> backend.sharedAddressStoreWrites.nonEmpty,
            "sharedLoadStoreLanes" -> (backend.loadLanes eq backend.storeByteLanes),
            "physicalQualification" -> false)
    }
    def write(out: Path, actual: Map[String, Any]): Unit =
        Files.writeString(out.resolve("actual-fourth-resource.json"), PostedBoardConfiguration.json(actual) + "\n")
}

object AreaFourthResourceConfigMain extends App {
    val p = AreaFourthResourceProfile
    var rejected = 0
    def reject(body: => Unit): Unit = {
        var failed = false
        try { body } catch { case _: IllegalArgumentException => failed = true }
        require(failed); rejected += 1
    }
    reject { p.requireOptions(p.options.reverse) }
    reject { p.requireOptions(p.options.dropRight(1)) }
    reject { FpgaNextProfileOptions.validate(p.options :+ "--shared-memory-address-state") }
    require(p.on.copy(sharedMemoryAddressState = false) == p.base.on)
    println(s"PASS_FOURTH_RESOURCE_CONFIG core=177 profile=94 options=74 negative=$rejected")
}

object AreaFourthResourceCpuMain extends App {
    require(args.length == 75)
    val p = AreaFourthResourceProfile
    p.requireOptions(args.drop(1).toSeq)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh combined CPU output required")
    p.write(out)
    var actual: Option[Map[String, Any]] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = FpgaNextBoardGsim.build(p.on, verifyConfiguration = true)
        // BoardSocGsim deliberately keeps its matching board private.
        val fields = dut.getClass.getDeclaredFields.filter(_.getType == classOf[MatchingManagedBoard])
        require(fields.length == 1)
        fields.head.setAccessible(true)
        val board = fields.head.get(dut).asInstanceOf[MatchingManagedBoard]
        actual = Some(AreaFourthResourceAudit.capture(board.platform))
        dut
    }, Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
    p.requireFabric(out)
    AreaFourthResourceAudit.write(out, actual.get)
    println("PASS_FOURTH_RESOURCE_ACTUAL_CPU core=177 profile=94 options=74 qualification_pending")
}

object AreaFourthResourceNativeMain extends App {
    require(args.length == 75)
    val p = AreaFourthResourceProfile
    p.requireOptions(args.drop(1).toSeq)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh native output required")
    FpgaNextMain.main(args)
    def read(name: String): ujson.Value = ujson.read(Files.readString(out.resolve(name)))
    require(read("profile.json") == p.contract("on_profile"))
    require(read("actual-timing-closure.json") == p.expected("timing_audit"))
    for ((file, key) <- Seq(("actual-held-alu-forwarding.json", "held"),
            ("actual-resident-memory.json", "resident"), ("actual-mac-raw-handoff.json", "mac")))
        require(read(file) == p.expected("existing_audits")(key))
    p.write(out)
    println("PASS_FOURTH_RESOURCE_NATIVE_ACTUAL core=177 profile=94 options=74 structure_check_pending")
}
