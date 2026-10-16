package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import soc.core.ooo._

/** Append-only candidate adapter. Never initializes old177/94 profile objects. */
object ReadyStoreQuery77Profile {
    val parentBytes = Files.readAllBytes(Paths.get("fpga/next/shared-lru76-profile.json"))
    val parent = ujson.read(new String(parentBytes, java.nio.charset.StandardCharsets.UTF_8))
    val contract = ujson.read(Files.readString(Paths.get("fpga/next/ready-store-query77-profile.json")))
    require(MessageDigest.getInstance("SHA-256").digest(parentBytes).map(b => f"${b & 0xff}%02x").mkString ==
        contract("parent76_sha256").str)
    require(parent("schema").str == "valence-shared-lru76-profile-v1")
    val offOptions = parent("on_options").arr.map(_.str).toSeq
    val options = offOptions :+ "--pending-ready-store-query"
    require(offOptions.size == 76 && options.size == 77 && options == contract("on_options").arr.map(_.str).toSeq)
    FpgaNextProfileOptions.validate(offOptions)
    FpgaNextProfileOptions.validate(options)
    val off = FpgaNextConfig.fromOptions(offOptions.toSet, defaultSelected = false)
    val on = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    def retained(value: Product, count: Int): ujson.Value =
        ujson.read(PostedBoardConfiguration.json(value.productElementNames.zip(value.productIterator).take(count).toMap))
    require(off.productArity == 95 && off.coreParams.productArity == 178)
    require(off.productElementNames.toSeq.dropRight(1) == parent("profile_fields").arr.map(_.str).toSeq)
    require(off.coreParams.productElementNames.toSeq.dropRight(1) == parent("core_fields").arr.map(_.str).toSeq)
    require(off.productElementName(94) == "pendingReadyStoreQuery" &&
        off.coreParams.productElementName(177) == "pendingReadyStoreQuery")
    require(!off.pendingReadyStoreQuery && !off.coreParams.pendingReadyStoreQuery)
    require(retained(off, 94) == parent("on_profile")("profile"))
    require(retained(off.coreParams, 177) == parent("on_profile")("core"))
    require(ujson.read(PostedBoardConfiguration.json(off.cache)) == parent("on_profile")("cache"))
    require(on == off.copy(pendingReadyStoreQuery = true))
    require(on.coreParams == off.coreParams.copy(pendingReadyStoreQuery = true))
    require(on.cache == off.cache && on.storage == off.storage && on.ddr == off.ddr && on.network == off.network)
    require(on.coreParams.pendingVirtualStoreProofSlots == 2 && on.coreParams.pendingStoreEarlyLoadCredits == 2)
    require(on.coreParams.pendingReadyStoreBypass && on.coreParams.registeredPendingStoreQuery &&
        on.coreParams.memoryPreparationHeadMask && !on.coreParams.memoryProofFrontier)
    require(on.issueWidth == 2 && on.coreParams.robEntries == 16 && on.coreParams.physicalRegs == 48 &&
        on.coreParams.memoryEntries == 4 && on.coreParams.tagBits == 64)
    // Historical ABI objects remain untouched; project new default-OFF values directly.
    for (file <- Seq("timing-ready73-profile.json", "area-fourth-resource74-profile.json",
        "shared-future75-profile.json", "shared-lru76-profile.json")) {
        val prior = ujson.read(Files.readString(Paths.get("fpga/next").resolve(file)))
        val oldOptions = prior("on_options").arr.map(_.str).toSeq
        FpgaNextProfileOptions.validate(oldOptions)
        val rebuilt = FpgaNextConfig.fromOptions(oldOptions.toSet, defaultSelected = false)
        require(!rebuilt.pendingReadyStoreQuery && !rebuilt.coreParams.pendingReadyStoreQuery)
        require(retained(rebuilt, 94) == prior("on_profile")("profile"))
        require(retained(rebuilt.coreParams, 177) == prior("on_profile")("core"))
        for ((name, actual) <- Seq("cache" -> rebuilt.cache, "storage" -> rebuilt.storage,
            "ddr" -> rebuilt.ddr, "network" -> rebuilt.network, "tags" -> rebuilt.tags))
            require(ujson.read(PostedBoardConfiguration.json(actual)) == prior("on_profile")(name))
    }
    def select(enabled: Boolean): FpgaNextConfig = if (enabled) on else off
}

/** Test-only assembly adapter: mirrors MachinePlatform -> IntegerCore constructor options. */
object ReadyStoreQuery77BackendFactory {
    def arguments(profile: FpgaNextConfig): Map[String, Boolean] = {
        val p = profile.coreParams
        Map("canonicalHandoff" -> (profile.cache.independentDemandAdmission && p.canonicalVirtualStoreOverlap),
            "registerCanonicalStoreEvent" -> p.registeredCanonicalStoreEvent,
            "retirementSlotIdentity" -> p.retirementSlotIdentity)
    }
    def create(profile: FpgaNextConfig, preselectRedirectTokenMatches: Boolean = false,
        shadowEarlyProofBind: Boolean = false, proofBankQuiesceIntent: Boolean = false,
        proofBankOwnerCleanup: Boolean = false, factorPreparedStorePool: Boolean = false,
        projectedRequestHead: Boolean = false, registeredMemoryPreparationDescriptor: Boolean = false, earlyLoadPreparationDescriptor: Boolean = false): IntegerBackend = {
        val args = arguments(profile)
        new IntegerBackend(profile.coreParams, canonicalHandoff = args("canonicalHandoff"),
            registerCanonicalStoreEvent = args("registerCanonicalStoreEvent"),
            retirementSlotIdentity = args("retirementSlotIdentity"),
            preselectRedirectTokenMatches = preselectRedirectTokenMatches, shadowEarlyProofBind = shadowEarlyProofBind,
            proofBankQuiesceIntent = proofBankQuiesceIntent, proofBankOwnerCleanup = proofBankOwnerCleanup,
            factorPreparedStorePool = factorPreparedStorePool, projectedRequestHead = projectedRequestHead,
            registeredMemoryPreparationDescriptor = registeredMemoryPreparationDescriptor,
            earlyLoadPreparationDescriptor = earlyLoadPreparationDescriptor)
    }
}

object ReadyStoreQuery77ConfigMain extends App {
    val p = ReadyStoreQuery77Profile
    for (profile <- Seq(p.off, p.on)) {
        val args = ReadyStoreQuery77BackendFactory.arguments(profile)
        require(args == Map("canonicalHandoff" -> true, "registerCanonicalStoreEvent" -> true,
            "retirementSlotIdentity" -> true))
        println("READY_STORE_QUERY77_BACKEND_ARGUMENTS " + PostedBoardConfiguration.json(args))
    }
    var rejected = 0
    def reject(body: => Unit): Unit = {
        var failed = false
        try { body } catch { case _: IllegalArgumentException => failed = true }
        require(failed); rejected += 1
    }
    reject { FpgaNextProfileOptions.validate(p.options :+ "--pending-ready-store-query") }
    reject { FpgaNextProfileOptions.validate(p.offOptions :+ "--pending-ready-store-query=false") }
    reject { p.on.coreParams.copy(pendingReadyStoreBypass = false) }
    reject { p.on.coreParams.copy(registeredPendingStoreQuery = false) }
    reject { p.on.coreParams.copy(memoryPreparationHeadMask = false) }
    reject { p.on.coreParams.copy(pendingVirtualStoreProofSlots = 1) }
    reject { p.on.coreParams.copy(pendingStoreEarlyLoadCredits = 1) }
    for (default <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected))
        require(!default.pendingReadyStoreQuery && !default.coreParams.pendingReadyStoreQuery)
    println(s"PASS_READY_STORE_QUERY77_CONFIG core=178 profile=95 options=77 negatives=$rejected")
}

/** Actual production backend constructor; component only, not a full CPU. */
class ReadyStoreQuery77ConstructorAudit(enabled: Boolean) extends Module {
    val profile = ReadyStoreQuery77Profile.select(enabled)
    val backend = Module(ReadyStoreQuery77BackendFactory.create(profile))
    val io = IO(chiselTypeOf(backend.io))
    io <> backend.io
    val actualArguments = ReadyStoreQuery77BackendFactory.arguments(profile)
    val actual = backend.p
    require(actual == profile.coreParams && actual.pendingReadyStoreQuery == enabled)
    require(backend.ledger.p == actual)
    require(backend.pendingStoreProof.get.state.length == 2 && backend.pendingStoreCredit.get.state.length == 2)
    require(backend.proofFrontier.isEmpty && actual.memoryEntries == 4)
}
object ReadyStoreQuery77ConstructorAuditMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)), "fresh-output enabled0|1")
    val out = Paths.get(args(0)); require(!Files.exists(out), "fresh output required")
    var actual: Option[OooParams] = None
    var actualArguments: Option[Map[String, Boolean]] = None
    ChiselStage.emitCHIRRTLFile({
        val wrapper = new ReadyStoreQuery77ConstructorAudit(args(1) == "1")
        actual = Some(wrapper.actual)
        actualArguments = Some(wrapper.actualArguments)
        wrapper
    }, Array("--target-dir", out.toString))
    require(actual.nonEmpty && actualArguments.nonEmpty)
    Files.writeString(out.resolve("actual-backend-arguments.json"), PostedBoardConfiguration.json(actualArguments.get) + "\n")
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(actual.get) + "\n")
}
