package ooo

import chisel3.experimental.{BaseModule, IntParam}
import soc.core.ooo._
import soc.ip.debug.{BscanRamTransport, JtagDebugReservation}
import soc.ip.clock.ManagedClockBuffer
import soc.ip.ethernet.QueuedGmiiFrameTx

/** Read-only native constructor observations. No production taps/state or old class replacement. */
object ThreeProofRowNativeActualAudit {
    def json(x: Any): ujson.Value = ujson.read(PostedBoardConfiguration.json(x))
    private def unique[T](instance: AnyRef, kind: Class[T]): T = {
        val found = scala.collection.mutable.ArrayBuffer.empty[java.lang.reflect.Field]
        var c: Class[_] = instance.getClass
        while (c != null) {
            found ++= c.getDeclaredFields.filter(f => !java.lang.reflect.Modifier.isStatic(f.getModifiers) && f.getType == kind)
            c = c.getSuperclass
        }
        require(found.size == 1, "actual constructor parameter absent/ambiguous: " + kind.getName)
        found.head.setAccessible(true)
        kind.cast(found.head.get(instance))
    }
    private def children(m: BaseModule): Seq[BaseModule] =
        classOf[BaseModule].getMethod("getIds").invoke(m).asInstanceOf[scala.collection.Iterable[_]]
            .collect { case x: BaseModule => x }.toSeq

    def capture(dut: FpgaNextSocTop, c: FpgaNextConfig,
        expectedFabric: ujson.Value, expectedThree: ujson.Value): Map[String, Any] = {
        val board = dut.board
        val p = board.platform
        val backend = p.core.core.core.backend
        val core = c.coreParams
        require(c.productArity == 95 && core.productArity == 178)
        require(p.core.core.core.p == core && backend.p == core && backend.ledger.p == core)
        require(core.pendingVirtualStoreProofSlots == 3 && core.pendingStoreEarlyLoadCredits == 2 && core.memoryEntries == 4)
        require(core.pendingReadyStoreQuery && core.robEntries == 16 && core.physicalRegs == 48 && core.tagBits == 64)
        val cache = p.privateCache.get.asInstanceOf[NonBlockingCoherentLineCache]
        val home = p.finalHome.get.asInstanceOf[MixedCoherentLineHome]
        val actualCache = unique(cache, classOf[CoherentCacheConcurrency])
        val actualDdr = unique(p, classOf[DdrBridgeConfig])
        require(actualCache == c.cache && actualDdr == c.ddr)
        require(core.cpuReturnConfig.map(x => (x.memoryEntries, x.storeBufferEntries, x.fpEnabled,
            x.handleBits, x.handleCount, x.tableEntries)) == Some((4, 2, true, 3, 7, 8)))
        require(backend.lsu.io.memory.request.bits.returnHandle.map(_.getWidth) == Some(3))
        require(cache.shareStoreWriteData && cache.registerProbeLookup && cache.localReadSelection)
        require(home.sharedLookupMatch && home.futureWayReservation && home.memoryScheduleOverlap)
        require(backend.multiplier.tags.isEmpty && backend.p.sharedMemoryAddressState)
        require(backend.sharedAddressLoadWrite.nonEmpty && backend.sharedAddressStoreWrites.nonEmpty)
        require(backend.loadLanes eq backend.storeByteLanes)
        require(backend.storeAddress.size == 16 && backend.storeAddress.forall(_.getWidth == 64))
        require(backend.pendingStoreProof.get.state.length == 3 && backend.pendingStoreCredit.get.state.length == 2)
        require(backend.proofFrontier.isEmpty && backend.lsu.slots.size == 4)
        require(backend.registerCanonicalStoreEvent && backend.retirementSlotIdentity)
        require(backend.canonicalStoreTracker.nonEmpty && backend.lsu.io.canonicalStoreOrigin.nonEmpty)
        val three = Map[String, Any]("schema" -> "ready-store-query77-actual-v1", "core" -> backend.p,
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
            "qualificationInherited" -> false, "physicalQualification" -> false)
        require(json(three) == expectedThree, "complete actual three-row native construction differs from qualified CPU")

        // Same reviewed common-domain capture helpers as the qualified CPU, with explicitly pinned precedence.
        val common = Map[String, Any]("cpu" -> p.core.core.core.p, "ddr" -> actualDdr, "cache" -> actualCache,
            "timingStages" -> TimingBatchActualAudit.capture(p, c),
            "zeroCycleCleanup" -> ZeroCycleCleanupActualAudit.capture(p, c),
            "ownerRow" -> OwnerRowActualAudit.capture(p, c),
            "eagerPrefix" -> EagerPrefixActualAudit.capture(p, c),
            "futureHome" -> FutureHomeActualAudit.capture(p, c),
            "headDrain" -> HeadDrainActualAudit.capture(p, c),
            "retirementIntent" -> RetirementIntentActualAudit.capture(p, c),
            "placedTiming" -> PlacedTimingActualAudit.capture(p, c),
            "memoryPreparationLocality" -> MemoryPreparationLocalityActualAudit.capture(p, c),
            "nearTermA" -> NearTermAActualAudit.capture(p, c),
            "heldAluIssueForwarding" -> HeldAluIntegrationActualAudit.capture(p, c),
            "residentMemoryPayloadReuse" -> ResidentMemoryIntegrationActualAudit.capture(p, c),
            "timingClosure" -> TimingClosureActualAudit.capture(p, c),
            "nativeRawHandoffRequested" -> c.triSpeedRawClockHandoff,
            "actualLsuOwners" -> backend.lsu.slots.size,
            "actualRegisterPorts" -> p.platformRouter.get.io.registers.size,
            "actualPacketRxOwners" -> p.packetDma.get.slotOwned.size,
            "actualPacketTxOwners" -> p.packetDma.get.txQueue.get.owned.size,
            "packetDmaClass" -> p.packetDma.get.getClass.getName,
            "memoryDmaClass" -> p.dma.getClass.getName,
            "jtagLoaderClass" -> p.jtagLoader.get.getClass.getName,
            "innerDmaArbiterClass" -> p.dmaArbiter.get.getClass.getName,
            "outerDmaArbiterClass" -> p.debugDmaArbiter.get.getClass.getName,
            "innerDmaClients" -> p.dmaArbiter.get.io.clients.size,
            "outerDmaClients" -> p.debugDmaArbiter.get.io.clients.size,
            "dmaArbitration" -> "(memoryCopy,packet)->regular;(regular,jtag)->laneAdapter",
            "dmaDataSizeBits" -> p.shared.io.dma.request.bits.size.getWidth,
            "dmaDataMaskBits" -> p.shared.io.dma.request.bits.mask.getWidth,
            "memoryDmaLinePresent" -> p.dma.io.line.nonEmpty,
            "localUartAbsent" -> p.uart.isEmpty,
            "localUartCdcAbsent" -> p.uartCdc.isEmpty)
        for ((key, value) <- common) require(json(value) == expectedFabric(key), "native common-domain mismatch: " + key)

        // Actual MAC activation, including the retained old audit's payload-width checks.
        val bank = board.nativeBank.getOrElse(throw new IllegalArgumentException("native managed bank absent"))
        val mac = bank.instantiatedTriSpeedMac.getOrElse(throw new IllegalArgumentException("actual tri-speed MAC absent"))
        require(c.experimentalTriSpeedEthernet && c.triSpeedRawClockHandoff && c.triSpeedTxFrameSlots == 2)
        require(board.triSpeedRawClockHandoff && bank.triSpeedRawClockHandoff && mac.rawClockHandoff)
        require(board.io.nativeGmac.get.triSpeedRgmii.nonEmpty && bank.triSpeedRgmii.nonEmpty)
        val handoff = mac.rawHandoff.getOrElse(throw new IllegalArgumentException("actual raw-clock handoff absent"))
        require(handoff.rawRxPayload.getWidth == 11 && handoff.rxPayload.getWidth == 11 &&
            handoff.rawTxByteStep.getWidth == 1 && handoff.txByteStep.getWidth == 1)
        val gates = children(mac).collect { case m: ManagedClockBuffer => m }
        require(gates.size == 2, "actual native MAC hardware clock gates absent/different")
        val tx = mac.tx match {
            case x: QueuedGmiiFrameTx => x
            case _ => throw new IllegalArgumentException("actual native MAC is not the queued two-bank TX")
        }
        require(tx.lengths.size == 2 && tx.producer.getWidth == 1 && tx.consumer.getWidth == 1)
        val serviceClasses = Map[String, Any](
            "gmacCsrClass" -> mac.csr.getClass.getName,
            "gmacFrontendClass" -> mac.frontend.getClass.getName,
            "gmacAdapterClass" -> mac.adapter.getClass.getName,
            "phyManagerClass" -> mac.phy.getClass.getName,
            "mediaTransitionClass" -> mac.media.getClass.getName,
            "mdioEngineClass" -> mac.mdio.getClass.getName,
            "mdioArbiterClass" -> mac.mdioOwner.getClass.getName,
            "uartAdmissionClass" -> bank.uart.proxy.getClass.getName)
        for ((key, value) <- serviceClasses) require(json(value) == expectedFabric(key), "actual native service class differs: " + key)
        val allCommon = common ++ serviceClasses
        val cpuOnlyKeys = Set("schema", "publishedSourceBaseCommit", "physicalComparisonCommit", "qualificationInherited",
            "rawMediaImplementedInGsim", "phyQualified", "productionPhysicalClocksSimulated", "cdcQualified",
            "bscanPrimitiveSimulated", "nativeMediaEnginesSimulated", "replacementBoundaries")
        require(expectedFabric.obj.keySet -- allCommon.keySet == cpuOnlyKeys,
            "CPU/native comparison boundary has unreviewed fields")

        val native = Map[String, Any]("actualTriSpeedMac" -> true, "actualRawHandoffPresent" -> true,
            "actualNativeMacClockGates" -> gates.size,
            "actualTxFrameSlots" -> tx.lengths.size,
            "actualTxProducerBits" -> tx.producer.getWidth, "actualTxConsumerBits" -> tx.consumer.getWidth,
            "macClass" -> mac.getClass.getName,
            "commonCoreAndFabricEqualQualifiedCpu" -> true,
            "physicalClockFrequencyMeasured" -> false, "physicalQualification" -> false)
        Map("schema" -> "three-proof-row-actual-native-audit-v1", "threeRow" -> three,
            "commonFabric" -> allCommon, "nativeBoundaries" -> native,
            "sourceDerivedNativeRomBoundary" -> Map("programmable" -> false, "vivadoMemories" -> true,
                "basis" -> "Pinned FpgaNextConfig.managedBoard invokes BoardSocTop preserved native defaults; not reflected runtime constructor values"),
            "excludedCpuOnlyObservationKeys" -> cpuOnlyKeys.toSeq.sorted)
    }

    /** Only top-level enumeration waits until emitSystemVerilogFile closes the top. */
    def captureClosedTop(dut: FpgaNextSocTop, partial: Map[String, Any]): Map[String, Any] = {
        val board = dut.board
        val p = board.platform
        // Actual BSCAN instance parameters, not merely requested config values or echoed flags.
        val scans = children(dut).collect { case m: BscanRamTransport => m }
        require(scans.size == 1 && children(dut).count(_.isInstanceOf[JtagDebugReservation]) == 0)
        require(scans.head.params == Map("ENABLE" -> IntParam(BigInt(1)), "JTAG_CHAIN" -> IntParam(BigInt(2))))
        require(board.jtagDmi.nonEmpty && board.jtagLinkUp.nonEmpty && p.io.jtagDmi.nonEmpty && p.jtagLoader.nonEmpty)
        require(board.jtagDmi.get.request.bits.address.getWidth == 7 && scans.head.io.dmi_req_address.getWidth == 7)
        val priorNative = partial("nativeBoundaries").asInstanceOf[Map[String, Any]]
        require(!priorNative.contains("actualBscanInstances"), "closed-top audit must merge once")
        val bscan = Map[String, Any]("actualBscanInstances" -> scans.size,
            "actualBscanEnable" -> scans.head.params("ENABLE").asInstanceOf[IntParam].value,
            "actualBscanChain" -> scans.head.params("JTAG_CHAIN").asInstanceOf[IntParam].value,
            "actualStandaloneTapInstances" -> 0, "actualRamLoaderPresent" -> p.jtagLoader.nonEmpty,
            "actualDmiAddressBits" -> board.jtagDmi.get.request.bits.address.getWidth,
            "bscanClass" -> scans.head.getClass.getName)
        partial + ("nativeBoundaries" -> (priorNative ++ bscan)) +
            ("auditPhases" -> Seq("closed-child-common-and-mac", "closed-top-bscan"))
    }
}
