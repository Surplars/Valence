package ooo

import chisel3._
import chisel3.experimental.{BaseModule, IntParam}
import chisel3.reflect.DataMirror
import soc.core.ooo._
import soc.ip.debug.{BscanRamTransport, JtagDebugReservation}
import soc.ip.ethernet.TriSpeedManagedGmac

/** Independent observations of the constructed experimental native hierarchy.
  * Historical values are frozen as shape expectations, never inherited qualification.
  */
object CombinedTimingPmpR1Audit {
    def json(x: Any): ujson.Value = ujson.read(PostedBoardConfiguration.json(x))
    private def children(m: BaseModule): Seq[BaseModule] =
        classOf[BaseModule].getMethod("getIds").invoke(m).asInstanceOf[scala.collection.Iterable[_]]
            .collect { case x: BaseModule => x }.toSeq
    private def descendants(m: BaseModule): Seq[BaseModule] = m +: children(m).flatMap(descendants)
    private def field(instance: AnyRef, name: String): Any = {
        var cls: Class[_] = instance.getClass
        var result: Option[java.lang.reflect.Field] = None
        while (cls != null && result.isEmpty) {
            result = cls.getDeclaredFields.find(f => f.getName == name || f.getName.endsWith("$$" + name))
            cls = cls.getSuperclass
        }
        val f = result.getOrElse(throw new IllegalArgumentException("actual field missing: " + name))
        f.setAccessible(true)
        f.get(instance)
    }
    private def leaves(name: String, data: Data): Seq[Map[String, Any]] = data match {
        case record: Record => record.elements.toSeq.flatMap { case (n, d) => leaves(name + "_" + n, d) }
        case vector: Vec[_] => vector.zipWithIndex.flatMap { case (d, i) => leaves(name + "_" + i, d) }.toSeq
        case _ => Seq(Map("name" -> name, "width" -> data.getWidth,
            "direction" -> DataMirror.directionOf(data).toString))
    }
    private val expectedPath = java.nio.file.Paths.get("docs/recovery/combined-timing-pmp-r1/expected-full-c1.json")
    def expected(enabled: Boolean): ujson.Value = {
        val value = ujson.read(java.nio.file.Files.readString(expectedPath))
        value
    }
    private def same(label: String, actual: Any, wanted: ujson.Value): Unit =
        require(json(actual) == wanted, s"combined timing frozen mismatch: $label")

    def capturePlatform(p: MachinePlatform, c: FpgaNextConfig, enabled: Boolean): Map[String, Any] = {
        val modules = descendants(p).distinct
        val backend = p.core.core.core.backend
        val dataAdapters = modules.collect { case m: DataTranslationAdapter => m }
        require(dataAdapters.size == 1 && p.core.observationTranslation.contains(dataAdapters.head))
        val dataAdapter = dataAdapters.head
        require(dataAdapter.registerNextLineDecision == enabled && dataAdapter.alignedNextLinePmp &&
            c.coreParams.dataNextLinePrefetch && c.coreParams.registeredTranslationHeads)
        val checkedIo = field(dataAdapter, "checked").asInstanceOf[Option[AnyRef]]
        require(checkedIo.nonEmpty, "registered checked request boundary must remain present")
        val checkedQueues = descendants(dataAdapter).collect {
            case q: soc.ip.bus.TwoEntryRegisterQueue[_] if checkedIo.exists(_ eq q.io) => q
        }
        require(checkedQueues.size == 1)
        def decisionBits(record: Data): Int = {
            val decision = record.asInstanceOf[Record].elements.get("nextLineDecision")
            require(decision.nonEmpty == enabled)
            decision.foreach { value =>
                val summary = value.asInstanceOf[PmpDecisionSummary]
                require(summary.entries == 16 && summary.hit.getWidth == 16 && summary.deny.getWidth == 16 &&
                    summary.defaultDeny.getWidth == 1 && summary.getWidth == 33)
            }
            decision.map(_.getWidth).getOrElse(0)
        }
        val authorize = dataAdapter.nextLineAuthorizationInstance.get
        require(authorize.alignedLinePmp && authorize.exportDecision == enabled &&
            authorize.decision.nonEmpty == enabled && authorize.eligible.nonEmpty == enabled)
        val exportingCheckers = descendants(authorize).collect { case m: PmpChecker if m.exportDecision => m }
        require(exportingCheckers.size == (if (enabled) 1 else 0))
        exportingCheckers.foreach(m => require(m.alignedLineAccess && m.decision.get.getWidth == 33))
        val pmpObservation = Map("headBits" -> decisionBits(checkedQueues.head.head),
            "tailBits" -> decisionBits(checkedQueues.head.tail), "exportingCheckers" -> exportingCheckers.size)
        val selectors = modules.collect { case m: ResidentMemoryPreparationSelector => m }
        val requests = modules.collect { case m: RegisteredRequestQueue => m }
        val proofs = modules.collect { case m: PendingVirtualStoreProof => m }
        val mirrors = modules.collect { case m: soc.ip.bus.MirroredHeadQueue[_] => m }
        val homeQueues = modules.collect {
            case m: soc.ip.bus.TwoEntryRegisterQueue[_] if m.instanceName == "homeRequests" => m
        }
        val frozen = expected(enabled)
        require(c.productArity == 96 && c.coreParams.productArity == 179)
        same("core", c.coreParams, frozen("core"))
        same("profile", c, frozen("profile"))
        same("core field order", c.coreParams.productElementNames.toSeq, frozen("fieldOrder")("core"))
        same("profile field order", c.productElementNames.toSeq, frozen("fieldOrder")("profile"))
        require(p.core.core.core.p == c.coreParams && backend.p == c.coreParams && backend.ledger.p == c.coreParams)
        require(backend.p.registeredMemoryRequests && backend.p.residentMemoryPayloadReuse &&
            backend.p.preparedStoreLookahead && !backend.p.postedPreparationPriority)
        require(selectors.size == 1 && selectors.head.rankResidentPriority)
        require(selectors.head.latePoolEnable == true && selectors.head.directSelectedRank == true)
        require(selectors.head.io.poolEnabled.nonEmpty == true)
        require(requests.size == 1 && requests.head.projectedHead == true && !requests.head.mirroredHead)
        require(backend.observationRequests.contains(requests.head))
        require(requests.head.io.count.getWidth == 3)
        require(mirrors.size == 1)
        mirrors.foreach { m =>
            require(m.residualStorage.nonEmpty, "projected head must retain residual sidecar storage")
            require(m.head.getWidth == requests.head.io.enq.bits.getWidth + 1,
                "projection must cover request and frozen-proof valid only")
        }
        require(homeQueues.size == 1)
        homeQueues.foreach(q => require(q.io.enq.bits.isInstanceOf[soc.bus.tilelink.TLBundleA]))
        require(backend.factorPreparedStorePool == true && !backend.preselectRedirectTokenMatches)
        require(backend.shadowEarlyProofBind == true && backend.proofBankQuiesceIntent == true &&
            backend.proofBankOwnerCleanup == true)
        require(proofs.size == 1 && proofs.head.ownerStateCleanup == true &&
            proofs.head.exposeLoadPreparedCandidate && proofs.head.checkBindPlanning == true)

        require(backend.pendingStoreProof.contains(proofs.head))
        require(backend.pendingStoreProof.get.state.length == 3 && backend.pendingStoreCredit.get.state.length == 2)
        require(backend.lsu.slots.size == 4 && backend.p.robEntries == 16 && backend.p.physicalRegs == 48)
        val helpers = modules.collect { case m: SharedTwoWordFetchPmp => m }
        val adapters = modules.collect { case m: InstructionTranslationAdapter => m }
        val caches = modules.collect { case m: NonBlockingCoherentLineCache => m }
        require(helpers.size == 2 && adapters.size == 1 && adapters.head.sharedTwoWordFetchPmp)
        require(p.sharedTwoWordFetchPmp && p.frontend.sharedTwoWordFetchPmp && p.disjointEvictionStoreOverlap)
        require(caches.size == 1 && caches.head.disjointEvictionStoreOverlap && !caches.head.splitCacheableBounds)
        val cache = caches.head
        require(cache.shareStoreWriteData && cache.registerProbeLookup && cache.localReadSelection)
        require(field(cache, "concurrency") == c.cache && field(p, "ddrBridge") == c.ddr)
        val geometry = Map("cache" -> field(cache, "concurrency"), "ddr" -> field(p, "ddrBridge"),
            "cacheLines" -> field(cache, "lines"), "cacheWays" -> field(cache, "ways"),
            "cacheBase" -> field(cache, "base"), "cacheBytes" -> field(cache, "bytes"),
            "proofRows" -> backend.pendingStoreProof.get.state.length,
            "earlyLoadCredits" -> backend.pendingStoreCredit.get.state.length, "lsuOwners" -> backend.lsu.slots.size)
        same("geometry", geometry, frozen("geometry"))
        val clocks = Map("cpu" -> c.cpuHz, "aon" -> c.aonHz, "uart" -> c.uartHz, "ddrUi" -> c.ddrUiHz)
        same("clocks", clocks, frozen("clockHz"))
        Map("schema" -> "combined-timing-pmp-r1-platform-actual-v1", "coreFields" -> c.coreParams.productArity,
            "profileFields" -> c.productArity, "core" -> backend.p, "profile" -> c,
            "pmpDecisionObservation" -> pmpObservation,
            "fieldOrder" -> Map("core" -> c.coreParams.productElementNames.toSeq,
                "profile" -> c.productElementNames.toSeq), "geometry" -> geometry, "clockHz" -> clocks,
            "featureFlags" -> Map("registerNextLineDecision" -> dataAdapter.registerNextLineDecision,
                "registeredHomeRequestBoundary" -> backend.p.registeredHomeRequestBoundary,
                "projectedRequestHead" -> requests.head.projectedHead,
                "factorPreparedStorePool" -> backend.factorPreparedStorePool,
                "proofBankControlDecoupling" -> backend.proofBankOwnerCleanup,
                "shadowEarlyProofBind" -> backend.shadowEarlyProofBind,
                "proofBankQuiesceIntent" -> backend.proofBankQuiesceIntent,
                "proofOwnerStateCleanup" -> proofs.head.ownerStateCleanup,
                "proofCheckBindPlanning" -> proofs.head.checkBindPlanning,
                "latePoolEnable" -> selectors.head.latePoolEnable,
                "directSelectedRank" -> selectors.head.directSelectedRank,
                "preselectRedirectTokenMatches" -> backend.preselectRedirectTokenMatches,
                "rankResidentPriority" -> selectors.head.rankResidentPriority,
                "sharedTwoWordFetchPmp" -> adapters.head.sharedTwoWordFetchPmp,
                "disjointEvictionStoreOverlap" -> cache.disjointEvictionStoreOverlap),
            "counts" -> Map("residentSelectors" -> selectors.size, "registeredRequestQueues" -> requests.size,
                "projectedHeadQueues" -> mirrors.size, "homeRequestQueues" -> homeQueues.size,
                "proofBanks" -> proofs.size, "sharedPmpHelpers" -> helpers.size, "nonBlockingCaches" -> caches.size),
            "qualificationInherited" -> false, "physicalQualification" -> false)
    }

    def capture(dut: FpgaNextSocTop, c: FpgaNextConfig, enabled: Boolean): Map[String, Any] = {
        val result = capturePlatform(dut.board.platform, c, enabled)
        val modules = descendants(dut).distinct
        val macs = modules.collect { case m: TriSpeedManagedGmac => m }
        val scans = modules.collect { case m: BscanRamTransport => m }
        require(dut.sharedTwoWordFetchPmp && dut.disjointEvictionStoreOverlap)
        require(dut.projectedRequestHead == true && dut.factorPreparedStorePool == true &&
            dut.proofBankControlDecoupling == true && dut.registerNextLineDecision == enabled)
        require(dut.board.sharedTwoWordFetchPmp && dut.board.disjointEvictionStoreOverlap)
        require(macs.size == 1 && macs.head.rawClockHandoff && macs.head.rawHandoff.nonEmpty &&
            dut.board.triSpeedRawClockHandoff && dut.board.nativeBank.get.triSpeedRawClockHandoff)
        require(scans.size == 1 && scans.head.params ==
            Map("ENABLE" -> IntParam(BigInt(1)), "JTAG_CHAIN" -> IntParam(BigInt(2))))
        require(!modules.exists(_.isInstanceOf[JtagDebugReservation]))
        val ports = DataMirror.modulePorts(dut).toSeq.flatMap { case (name, data) => leaves(name, data) }
        require(ports.size == 76)
        same("native ports", ports, expected(enabled)("topPorts"))
        val boundary = Map("rawHandoffPresent" -> macs.head.rawHandoff.nonEmpty,
            "bscanChain" -> scans.head.params("JTAG_CHAIN").asInstanceOf[IntParam].value,
            "ramLoaderPresent" -> dut.board.platform.jtagLoader.nonEmpty,
            "nativeMacPhysicalGenericsApplied" -> false)
        require(dut.board.jtagDmi.nonEmpty)
        same("native boundaries", boundary, expected(enabled)("nativeBoundaries"))
        val native = result ++ Map("schema" -> "combined-timing-pmp-r1-native-actual-v1", "topPorts" -> ports,
            "nativeBoundaries" -> boundary)
        if (!enabled) {
            val saved = ujson.read(java.nio.file.Files.readString(java.nio.file.Paths.get(
                "docs/recovery/combined-timing-pmp-r1/expected-pmp-off-native.json")))
            same("complete frozen full-C1 actual observation with explicit pmp-off field", native, saved)
        }
        native
    }
}
