package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** New ABI entrypoint. Never initializes historical 177/94 profile or audit singletons. */
object ReadyStoreQuery77CpuMain extends App {
    val p = ReadyStoreQuery77Profile
    require(args.length == 78 && args.drop(1).toSeq == p.options, "exact ordered 77 options required")
    require(p.on.productArity == 95 && p.on.coreParams.productArity == 178)
    require(p.on.productElementNames.toSeq == p.contract("profile_fields").arr.map(_.str).toSeq)
    require(p.on.coreParams.productElementNames.toSeq == p.contract("core_fields").arr.map(_.str).toSeq)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh fullCPU77 output required")
    def json(v: Any): ujson.Value = ujson.read(PostedBoardConfiguration.json(v))
    val core = json(p.on.coreParams)
    def expand(v: ujson.Value): ujson.Value = v match {
        case obj: ujson.Obj if obj == p.parent("on_profile")("core") => core
        case obj: ujson.Obj if obj.obj.keySet == Set("$timing_core") =>
            require(obj("$timing_core").str == "on"); core
        case obj: ujson.Obj => ujson.Obj.from(obj.obj.toSeq.map { case (k, x) =>
            if (k == "coreFields") { require(x.num == 177); k -> ujson.Num(178) }
            else if (k == "profileFields") { require(x.num == 94); k -> ujson.Num(95) }
            else if (k == "coreNames") {
                require(x == p.parent("core_fields")); k -> p.contract("core_fields")
            } else if (k == "profileNames") {
                require(x == p.parent("profile_fields")); k -> p.contract("profile_fields")
            } else k -> expand(x)
        })
        case arr: ujson.Arr => ujson.Arr.from(arr.arr.map(expand))
        case scalar => scalar
    }
    val expectedProfile = ujson.read(p.parent("on_profile").render())
    expectedProfile("profile") = json(p.on)
    expectedProfile("core") = core
    require(json(PostedBoardConfiguration.document(p.on)) == expectedProfile)
    PostedBoardConfiguration.write(p.on, out.toString)
    Files.writeString(out.resolve("options.txt"), p.options.mkString("", "\n", "\n"))
    Files.writeString(out.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(Map(
        "core" -> p.on.coreParams.productElementNames.toSeq,
        "profile" -> p.on.productElementNames.toSeq)) + "\n")
    var actual: Option[Map[String, Any]] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = FpgaNextBoardGsim.build(p.on, verifyConfiguration = true)
        val fields = dut.getClass.getDeclaredFields.filter(_.getType == classOf[MatchingManagedBoard])
        require(fields.length == 1)
        fields.head.setAccessible(true)
        val platform = fields.head.get(dut).asInstanceOf[MatchingManagedBoard].platform
        val backend = platform.core.core.core.backend
        val cache = platform.privateCache.get.asInstanceOf[NonBlockingCoherentLineCache]
        val home = platform.finalHome.get.asInstanceOf[MixedCoherentLineHome]
        val cacheFields = cache.getClass.getDeclaredFields.filter(_.getType == classOf[CoherentCacheConcurrency])
        require(cacheFields.length == 1)
        cacheFields.head.setAccessible(true)
        val actualCache = cacheFields.head.get(cache).asInstanceOf[CoherentCacheConcurrency]
        require(platform.core.core.core.p == p.on.coreParams && backend.p == p.on.coreParams)
        require(backend.ledger.p == backend.p && backend.p.pendingReadyStoreQuery)
        require(actualCache == p.on.cache && actualCache.futureHomeWayReservation && actualCache.storePrefetchLruVictim)
        require(cache.shareStoreWriteData && cache.registerProbeLookup && cache.localReadSelection)
        require(home.sharedLookupMatch && home.futureWayReservation && home.memoryScheduleOverlap)
        require(backend.multiplier.tags.isEmpty && backend.p.sharedMemoryAddressState)
        require(backend.sharedAddressLoadWrite.nonEmpty && backend.sharedAddressStoreWrites.nonEmpty)
        require(backend.loadLanes eq backend.storeByteLanes)
        require(backend.storeAddress.size == 16 && backend.storeAddress.forall(_.getWidth == 64))
        require(backend.pendingStoreProof.get.state.length == 2 && backend.pendingStoreCredit.get.state.length == 2)
        require(backend.proofFrontier.isEmpty && backend.lsu.slots.size == 4)
        require(backend.registerCanonicalStoreEvent && backend.retirementSlotIdentity)
        require(backend.canonicalStoreTracker.nonEmpty && backend.lsu.io.canonicalStoreOrigin.nonEmpty)
        actual = Some(Map("schema" -> "ready-store-query77-actual-v1", "core" -> backend.p,
            "cache" -> actualCache, "sharedStoreWriteData" -> cache.shareStoreWriteData,
            "sharedLookupMatch" -> home.sharedLookupMatch, "futureHomeWayReservation" -> home.futureWayReservation,
            "storePrefetchLruVictim" -> actualCache.storePrefetchLruVictim,
            "boundedMultiplierTagsAbsent" -> backend.multiplier.tags.isEmpty,
            "sharedMemoryAddressState" -> backend.p.sharedMemoryAddressState,
            "sharedAddressLoadWritePresent" -> backend.sharedAddressLoadWrite.nonEmpty,
            "sharedAddressStoreWritesPresent" -> backend.sharedAddressStoreWrites.nonEmpty,
            "sharedLoadStoreLanes" -> (backend.loadLanes eq backend.storeByteLanes),
            "proofRows" -> backend.pendingStoreProof.get.state.length,
            "earlyLoadCredits" -> backend.pendingStoreCredit.get.state.length,
            "lsuOwners" -> backend.lsu.slots.size,
            "registeredCanonicalStoreEvent" -> backend.registerCanonicalStoreEvent,
            "retirementSlotIdentity" -> backend.retirementSlotIdentity,
            "canonicalStoreOriginPresent" -> backend.lsu.io.canonicalStoreOrigin.nonEmpty,
            "qualificationInherited" -> false, "physicalQualification" -> false))
        dut
    }, Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
    require(ujson.read(Files.readString(out.resolve("actual-fabric.json"))) == expand(p.parent("on_fabric")))
    require(ujson.read(Files.readString(out.resolve("actual-core-parameters.json"))) == core)
    for ((key, value) <- p.parent("derived_resource_expectations").obj)
        require(json(actual.get)(key) == value, "actual derived resource mismatch: " + key)
    Files.writeString(out.resolve("actual-ready-store-query77.json"), json(actual.get).render(indent = 2) + "\n")
    println("PASS_READY_STORE_QUERY77_ACTUAL_CPU core=178 profile=95 options=77 qualification_pending")
}
