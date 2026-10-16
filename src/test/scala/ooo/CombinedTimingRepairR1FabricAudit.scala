package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._
import soc.bus.tilelink.TLParams

/** Versioned repair observations retain every unrelated frozen fabric check.
  * Actual descriptor-selector replacement is recorded without rewriting the evidence;
  * only the explicitly checked selector fields are normalized for frozen comparison.
  * The original audit remains the descriptor-OFF path.
  */
object CombinedTimingRepairR1FabricAudit {
    private var actual: Option[Map[String, Any]] = None
    private def unique[T](instance: AnyRef, kind: Class[T]): T = {
        val fields = scala.collection.mutable.ArrayBuffer.empty[java.lang.reflect.Field]
        var declaring: Class[_] = instance.getClass
        while (declaring != null) {
            fields ++= declaring.getDeclaredFields.filter(f =>
                !java.lang.reflect.Modifier.isStatic(f.getModifiers) && f.getType == kind)
            declaring = declaring.getSuperclass
        }
        require(fields.size == 1, "actual constructor field absent/ambiguous: " + kind.getName)
        fields.head.setAccessible(true)
        kind.cast(fields.head.get(instance))
    }
    def capture(board: MatchingManagedBoard, expected: FpgaNextConfig): Unit = {
        require(board.registeredMemoryPreparationDescriptor,
            "repair fabric audit requires the descriptor-enabled construction")
        val p = board.platform
        val cache = p.privateCache.get
        val actualCore = p.core.core.core.p
        val actualDdr = unique(p, classOf[DdrBridgeConfig])
        val actualCache = unique(cache, classOf[CoherentCacheConcurrency])
        require(actualCore == expected.coreParams && actualDdr == expected.ddr && actualCache == expected.cache)
        HeadDrainActualAudit.requireShape(expected)
        require(actualCore.taggedStoreReturns == expected.taggedStoreReturns)
        require(actualCore.cpuReturnConfig.map(c => (c.memoryEntries, c.storeBufferEntries, c.fpEnabled,
            c.handleBits, c.handleCount, c.tableEntries)) ==
            (if (expected.taggedStoreReturns) Some((4, 2, true, 3, 7, 8)) else None),
            "tagged board return namespace differs from exact 4/2/1 domain")
        require(p.core.core.core.backend.lsu.io.memory.request.bits.returnHandle.map(_.getWidth) ==
            (if (expected.taggedStoreReturns) Some(3) else None), "actual LSU optional port width changed")
        require(p.packetDma.get.txQueue.get.owned.size == expected.network.postedTxSlots)
        require(p.packetDma.get.slotOwned.size == expected.network.postedRxSlots)
        require(p.dmaArbiter.get.io.clients.size == 2 && p.debugDmaArbiter.get.io.clients.size == 2)
        actual = Some(Map(
            "schema" -> "matching-board-fabric-combined-timing-repair-r1-v1",
            "publishedSourceBaseCommit" -> "9937714cee13e26e54b8aabc4d149585af22245b",
            "physicalComparisonCommit" -> "b1bb5d863f7ad5b034f148b18968d19e46ace75b",
            "qualificationInherited" -> false,
            "cpu" -> actualCore, "ddr" -> actualDdr, "cache" -> actualCache,
            "timingStages" -> TimingBatchActualAudit.capture(p, expected),
            "zeroCycleCleanup" -> ZeroCycleCleanupActualAudit.capture(p, expected),
            "ownerRow" -> OwnerRowActualAudit.capture(p, expected),
            "eagerPrefix" -> EagerPrefixActualAudit.capture(p, expected),
            "futureHome" -> FutureHomeActualAudit.capture(p, expected),
            "headDrain" -> HeadDrainActualAudit.capture(p, expected),
            "retirementIntent" -> RetirementIntentActualAudit.capture(p, expected),
            "placedTiming" -> PlacedTimingActualAudit.capture(p, expected),
            "memoryPreparationLocality" -> MemoryPreparationLocalityActualAudit.capture(p, expected),
            "nearTermA" -> NearTermAActualAudit.capture(p, expected),
            "heldAluIssueForwarding" -> HeldAluIntegrationActualAudit.capture(p, expected),
            "residentMemoryPayloadReuse" -> ResidentMemoryIntegrationActualAudit.capture(p, expected),
            "timingClosure" -> TimingClosureActualAudit.capture(p, expected),
            "nativeRawHandoffRequested" -> expected.triSpeedRawClockHandoff,
            "rawMediaImplementedInGsim" -> false,
            "phyQualified" -> false,
            "actualLsuOwners" -> p.core.core.core.backend.lsu.slots.size,
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
            "localUartCdcAbsent" -> p.uartCdc.isEmpty,
            "gmacCsrClass" -> board.gmac.csr.getClass.getName,
            "gmacFrontendClass" -> board.gmac.frontend.getClass.getName,
            "gmacAdapterClass" -> board.gmac.adapter.getClass.getName,
            "phyManagerClass" -> board.gmac.phy.getClass.getName,
            "mediaTransitionClass" -> board.gmac.media.getClass.getName,
            "mdioEngineClass" -> board.gmac.mdio.getClass.getName,
            "mdioArbiterClass" -> board.gmac.mdioOwner.getClass.getName,
            "uartAdmissionClass" -> board.uartAdmission.getClass.getName,
            "productionPhysicalClocksSimulated" -> false,
            "cdcQualified" -> false,
            "bscanPrimitiveSimulated" -> false,
            "nativeMediaEnginesSimulated" -> false,
            "replacementBoundaries" -> Seq(
                "VivadoBootRom -> same-latency programmable synchronous ROM",
                "UART CDC/native50MHz UART and CMU CDC/native50MHz CMU -> external one-credit register services",
                "GMAC media/CDC frame/config/rate/stop/counter/level interfaces -> explicit CPU-domain services",
                "recovered-clock watchdog -> CPU-visible service level",
                "RGMII/PHY pins -> frame service and Clause22 MDIO pad responder",
                "BSCAN/TCK transport/CDC -> synchronous DMI/link service",
                "asynchronous cold-reset assertion -> synchronous assertion with three CPU release stages",
                "MIG/UI250MHz/DDR device -> unchanged independent-RW R32/B32 AXI service")))
        val frozen = ujson.read(Files.readString(Paths.get(
            "docs/recovery/combined-timing-r1/expected-fabric-baseline.json")))
        def selectArm(value: ujson.Value): Unit = value match {
            case obj: ujson.Obj =>
                if (obj.value.contains("registeredHomeRequestBoundary")) {
                    require(obj.value.keySet == CombinedTimingR1Audit.expected(false)("core").obj.keySet,
                        "home extension must identify a complete frozen core product")
                    obj("registeredHomeRequestBoundary") = ujson.Bool(expected.registeredHomeRequestBoundary)
                }
                obj.value.values.foreach(selectArm)
            case arr: ujson.Arr => arr.value.foreach(selectArm)
            case _ =>
        }
        selectArm(frozen)
        // Preserve raw actual counts/classes in actual-fabric.json. Normalize a separate
        // comparison object only after proving the exact one-for-one selector replacement.
        val normalized = ujson.read(json(actual.get))
        require(normalized("schema") == ujson.Str("matching-board-fabric-combined-timing-repair-r1-v1") &&
            frozen("schema") == ujson.Str("matching-board-fabric-combined-timing-r1-v1"))
        normalized("schema") = ujson.Str("matching-board-fabric-combined-timing-r1-v1")
        val resident = normalized("residentMemoryPayloadReuse")
        require(resident("schema") == ujson.Str("actual-resident-memory-integration-repair-r1-v1"))
        require(resident("residentSelectorCount") == ujson.Num(0) &&
            resident("residentSelectorClasses") == ujson.Arr())
        require(resident("descriptorSelectorCount") == ujson.Num(1) &&
            resident("descriptorSelectorClasses") ==
                ujson.Arr(ujson.Str("soc.core.ooo.MemoryPreparationDescriptorSelector")))
        resident("schema") = ujson.Str("actual-resident-memory-integration-v1")
        resident("residentSelectorCount") = ujson.Num(1)
        resident("residentSelectorClasses") =
            ujson.Arr(ujson.Str("soc.core.ooo.ResidentMemoryPreparationSelector"))
        resident.obj.remove("descriptorSelectorCount")
        resident.obj.remove("descriptorSelectorClasses")
        require(normalized == frozen, "complete repair fabric differs outside the explicit selector replacement")
    }
    private def quote(s: String): String = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    private def json(v: Any): String = v match {
        case null => "null"
        case s: String => quote(s)
        case b: Boolean => b.toString
        case n: Int => n.toString
        case n: Long => n.toString
        case n: BigInt => n.toString
        case o: Option[_] => o.map(json).getOrElse("null")
        case m: collection.Map[_, _] => m.toSeq.sortBy(_._1.toString)
            .map { case (k, x) => quote(k.toString) + ":" + json(x) }.mkString("{", ",", "}")
        case s: Seq[_] => s.map(json).mkString("[", ",", "]")
        case p: Product => json(p.productElementNames.zip(p.productIterator).toMap)
        case _ => throw new IllegalArgumentException("unsupported audit value")
    }
    def write(directory: String): Unit = {
        require(actual.nonEmpty, "the actual matching envelope was not constructed")
        Files.writeString(Paths.get(directory, "actual-fabric.json"), json(actual.get) + "\n")
        PostedBoardConfiguration.writeCore(actual.get("cpu").asInstanceOf[OooParams], directory)
        Files.writeString(Paths.get(directory, "actual-timing-closure.json"),
            json(actual.get("timingClosure")) + "\n")
        Files.writeString(Paths.get(directory, "actual-resident-memory.json"),
            json(actual.get("residentMemoryPayloadReuse")) + "\n")
    }

    // Independent versioned shape guards; historical ABI objects remain unchanged.
    private object VersionedShapeChecks {
        def requireShape(c: FpgaNextConfig): Unit = {
            val frozen = CombinedTimingR1Audit.expected(c.registeredHomeRequestBoundary)
            require(c.productArity == 96 && c.coreParams.productArity == 179)
            require(CombinedTimingR1Audit.json(c) == frozen("profile"))
            require(CombinedTimingR1Audit.json(c.coreParams) == frozen("core"))
            require(CombinedTimingR1Audit.json(c.productElementNames.toSeq) == frozen("fieldOrder")("profile"))
            require(CombinedTimingR1Audit.json(c.coreParams.productElementNames.toSeq) == frozen("fieldOrder")("core"))
        }
    }
    private object VersionedProfileAbi {
        def requireLive(c: FpgaNextConfig): Unit = VersionedShapeChecks.requireShape(c)
        def requireLive(p: OooParams): Unit = {
            val frozen = CombinedTimingR1Audit.expected(p.registeredHomeRequestBoundary)
            require(p.productArity == 179 && CombinedTimingR1Audit.json(p) == frozen("core"))
            require(CombinedTimingR1Audit.json(p.productElementNames.toSeq) == frozen("fieldOrder")("core"))
        }
    }

    object TimingBatchActualAudit {
        def requireQueryStage(expected: Boolean, bank: Option[PendingVirtualStoreProof]): Boolean = {
            val actual = bank.exists(_.registerQuery)
            require(actual == expected, "actual pending query stage differs from its OooParams flag")
            actual
        }
        def requireFetchPorts(enabled: Boolean, ports: (String, Boolean)*): Unit = {
            require(ports.nonEmpty, "fetch phase audit requires actual optional ports")
            ports.foreach { case (name, present) =>
                require(present == enabled, s"fetch phase optional port mismatch: $name")
            }
        }
        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            VersionedShapeChecks.requireShape(expected)
            val mapped = platform.core
            val machine = mapped.core
            val core = machine.core
            val backend = core.backend
            val adapter = mapped.observationTranslation.getOrElse(
                throw new IllegalArgumentException("actual staged data adapter is absent"))
            val actual = core.p
            require(actual == expected.coreParams && backend.p == actual,
                "emitted core/backend differs from the complete requested profile")
            require(backend.registerCanonicalStoreEvent == actual.registeredCanonicalStoreEvent &&
                adapter.registerCanonicalStoreEvent == actual.registeredCanonicalStoreEvent,
                "actual canonical event producer/backend configuration differs")
            val packet = core.fetchPacket.getOrElse(
                throw new IllegalArgumentException("actual registered fetch packet is absent"))
            require(packet.eagerPrefixSelect == actual.eagerFetchPrefixSelect,
                "actual selected packet eager prefix mode differs")
            require(packet.alignedPermissionStage == actual.alignedFetchPermissionStage &&
                platform.frontend.boundedRequestFrontier == actual.alignedFetchPermissionStage,
                "actual fetch packet/frontend mode differs")
            requireFetchPorts(actual.alignedFetchPermissionStage,
                "core offsets" -> core.io.instructionFaultOffsets.nonEmpty,
                "core frontier" -> core.io.fetchRequestFrontier.nonEmpty,
                "core suppress" -> core.io.suppressFetchRequest.nonEmpty,
                "machine offsets" -> machine.io.instructionFaultOffsets.nonEmpty,
                "machine frontier" -> machine.io.fetchRequestFrontier.nonEmpty,
                "machine suppress" -> machine.io.suppressFetchRequest.nonEmpty,
                "mapped offsets" -> mapped.io.instructionFaultOffsets.nonEmpty,
                "mapped frontier" -> mapped.io.fetchRequestFrontier.nonEmpty,
                "mapped suppress" -> mapped.io.suppressFetchRequest.nonEmpty,
                "packet phase input" -> packet.io.phaseInput.nonEmpty,
                "packet frontier" -> packet.io.requestFrontier.nonEmpty,
                "packet suppress" -> packet.io.suppressRequest.nonEmpty,
                "frontend frontier" -> platform.frontend.io.requestFrontier.nonEmpty,
                "frontend suppress" -> platform.frontend.io.suppressRequest.nonEmpty)
            require(backend.pendingStoreProof.nonEmpty == actual.pendingVirtualStoreProof)
            val queryRegistered = requireQueryStage(actual.registeredPendingStoreQuery, backend.pendingStoreProof)
            Map("schema" -> "timing-batch-actual-stage-parameters-v1",
                "registeredPendingStoreQuery" -> queryRegistered,
                "proofBankPresent" -> backend.pendingStoreProof.nonEmpty,
                "canonicalBackendRegistered" -> backend.registerCanonicalStoreEvent,
                "canonicalAdapterRegistered" -> adapter.registerCanonicalStoreEvent,
                "fetchPacketAlignedStage" -> packet.alignedPermissionStage,
                "fetchFrontendBoundedRequest" -> platform.frontend.boundedRequestFrontier,
                "coreFaultOffsetBits" -> core.io.instructionFaultOffsets.map(_(0).getWidth).getOrElse(0),
                "proofRows" -> actual.pendingVirtualStoreProofSlots,
                "earlyLoadCredits" -> actual.pendingStoreEarlyLoadCredits,
                "taggedStoreReturns" -> actual.taggedStoreReturns,
                "coreFields" -> actual.productArity,
                "profileFields" -> expected.productArity)
        }
        def write(actual: Map[String, Any], directory: String): Unit = {
            def atom(value: Any): String = value match {
                case text: String => "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
                case value: Boolean => value.toString
                case value: Int => value.toString
                case _ => throw new IllegalArgumentException("unsupported actual-stage value")
            }
            val json = actual.toSeq.sortBy(_._1).map { case (key, value) =>
                atom(key) + ":" + atom(value)
            }.mkString("{", ",", "}\n")
            Files.writeString(Paths.get(directory, "actual-stage-parameters.json"), json)
        }
    }

    object ZeroCycleCleanupActualAudit {
        private def geometry(tl: TLParams, axiAddressWidth: Int, axiIdWidth: Int,
            maxBurstBeats: Int, axiAddressBase: BigInt, axiWindowBytes: BigInt,
            writeCollectionFlow: Boolean, lineReadChannel: Boolean,
            localPayloadWriteEnable: Boolean): Map[String, Any] = Map(
            "tlParams" -> tl, "sizeBits" -> tl.sizeBits, "sinkBits" -> tl.sinkBits,
            "sourceBits" -> tl.sourceBits, "addressBits" -> tl.addrWidth, "dataBits" -> tl.dataWidth,
            "axiAddressBits" -> axiAddressWidth, "axiIdBits" -> axiIdWidth,
            "maxBurstBeats" -> maxBurstBeats, "axiAddressBase" -> axiAddressBase,
            "axiWindowBytes" -> axiWindowBytes, "writeCollectionFlow" -> writeCollectionFlow,
            "lineReadChannel" -> lineReadChannel, "localPayloadWriteEnable" -> localPayloadWriteEnable)

        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            val backend = platform.core.core.core.backend
            val actualCore = platform.core.core.core.p
            HeadDrainActualAudit.requireShape(expected)
            require(actualCore == expected.coreParams)
            require(backend.p.directRegisteredExecutionOperands == expected.directRegisteredExecutionOperands &&
                backend.p.registeredIssueExecute, "actual registered execution operand option differs")
            val wrapper = platform.ddrManagerInstance.getOrElse(
                throw new IllegalArgumentException("actual external DDR manager was not constructed"))
            val manager = wrapper.outstandingInstance.getOrElse(
                throw new IllegalArgumentException("actual DDR slot manager was not constructed"))
            val wrapperGeometry = geometry(wrapper.tlParams, wrapper.axiAddressWidth, wrapper.axiIdWidth,
                wrapper.maxBurstBeats, wrapper.axiAddressBase, wrapper.axiWindowBytes,
                wrapper.writeCollectionFlow, wrapper.lineReadChannel, wrapper.localPayloadWriteEnable) ++ Map(
                "maxOutstanding" -> wrapper.maxOutstanding, "maxOutstandingWrites" -> wrapper.maxOutstandingWrites,
                "unorderedResponses" -> wrapper.unorderedResponses)
            val managerGeometry = geometry(manager.tlParams, manager.axiAddressWidth, manager.axiIdWidth,
                manager.maxBurstBeats, manager.axiAddressBase, manager.axiWindowBytes,
                manager.writeCollectionFlow, manager.lineReadChannel, manager.localPayloadWriteEnable) ++ Map(
                "maxOutstanding" -> manager.maxOutstanding, "maxOutstandingWrites" -> manager.maxOutstandingWrites,
                "unorderedResponses" -> manager.unorderedResponses)
            val required = geometry(soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 5),
                32, 4, 16, BigInt("80200000", 16), BigInt(1) << 31, true, true,
                expected.localPayloadWriteEnable) ++ Map("maxOutstanding" -> 4,
                "maxOutstandingWrites" -> 2, "unorderedResponses" -> true)
            require(wrapperGeometry == required && managerGeometry == required,
                "actual DDR wrapper/manager constructor differs from exact four-slot geometry")
            require(wrapper.io.tl.a.bits.source.getWidth == 5 && manager.io.tl.a.bits.source.getWidth == 5 &&
                wrapper.io.tl.a.bits.size.getWidth == 3 && manager.io.tl.a.bits.size.getWidth == 3 &&
                wrapper.io.tl.d.bits.sink.getWidth == 1 && manager.io.tl.d.bits.sink.getWidth == 1 &&
                wrapper.io.axi.ar.bits.id.getWidth == 4 && manager.io.axi.ar.bits.id.getWidth == 4)
            require(manager.slots.size == 4, "actual DDR slot count differs")
            val slots = manager.slots.map { slot =>
                val actual = geometry(slot.tlParams, slot.axiAddressWidth, slot.axiIdWidth,
                    slot.maxBurstBeats, slot.axiAddressBase, slot.axiWindowBytes,
                    slot.writeCollectionFlow, slot.lineReadChannel, slot.localPayloadWriteEnable)
                require(actual == required -- Seq("maxOutstanding", "maxOutstandingWrites", "unorderedResponses"),
                    "actual DDR slot constructor differs from its manager")
                require(slot.io.tl.a.bits.source.getWidth == 5 && slot.io.tl.a.bits.size.getWidth == 3 &&
                    slot.io.tl.d.bits.sink.getWidth == 1 && slot.io.axi.ar.bits.id.getWidth == 4 &&
                    slot.io.lineMode.nonEmpty && slot.io.lineData.get.getWidth == 512 && slot.payloadBanks.size == 8,
                    "actual DDR slot ports or payload-bank count differ")
                actual + ("payloadBanks" -> slot.payloadBanks.size)
            }
            Map("schema" -> "actual-zero-cycle-cleanup-v1",
                "directRegisteredExecutionOperands" -> backend.p.directRegisteredExecutionOperands,
                "registeredIssueExecute" -> backend.p.registeredIssueExecute,
                "wrapper" -> wrapperGeometry, "manager" -> managerGeometry,
                "slotCount" -> manager.slots.size, "slots" -> slots)
        }
    }

    object OwnerRowActualAudit {
        private def flags(row: Boolean, localEnable: Boolean, lineRead: Boolean): Map[String, Any] = {
            require(!row || (localEnable && lineRead), "actual local payload row lacks its prerequisites")
            Map("localPayloadWriteRow" -> row, "localPayloadWriteEnable" -> localEnable,
                "lineReadChannel" -> lineRead)
        }

        private def geometry(tl: TLParams, addressWidth: Int, idWidth: Int, beats: Int,
            base: BigInt, window: BigInt, collection: Boolean): Map[String, Any] =
            Map("tl" -> tl, "addressWidth" -> addressWidth, "idWidth" -> idWidth,
                "beats" -> beats, "base" -> base, "window" -> window, "collection" -> collection)

        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            val core = platform.core.core.core
            val backend = core.backend
            HeadDrainActualAudit.requireShape(expected)
            require(core.p == expected.coreParams && backend.p == core.p,
                "actual owner-row core differs from the complete requested profile")
            require(backend.shareCanonicalStoreOwnerMatch == backend.p.sharedCanonicalStoreOwnerMatch &&
                backend.shareCanonicalStoreOwnerMatch == expected.sharedCanonicalStoreOwnerMatch,
                "actual shared canonical-store owner comparator differs from its OooParams flag")
            require(!backend.shareCanonicalStoreOwnerMatch || backend.p.canonicalVirtualStoreOverlap,
                "actual shared canonical-store owner comparator lacks canonical overlap")

            val wrapper = platform.ddrManagerInstance.getOrElse(
                throw new IllegalArgumentException("actual external DDR manager was not constructed"))
            val manager = wrapper.outstandingInstance.getOrElse(
                throw new IllegalArgumentException("actual DDR slot manager was not constructed"))
            require(Set(8, 16).contains(wrapper.maxBurstBeats) && wrapper.maxBurstBeats == expected.ddr.maxBurstBeats,
                "actual SoC DDR burst must match the requested 8 or 16 beat geometry")
            val requiredGeometry = geometry(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 5),
                32, 4, wrapper.maxBurstBeats, BigInt("80200000", 16), BigInt(1) << 31,
                expected.ddr.writeCollectionFlow)
            require(geometry(wrapper.tlParams, wrapper.axiAddressWidth, wrapper.axiIdWidth,
                wrapper.maxBurstBeats, wrapper.axiAddressBase, wrapper.axiWindowBytes,
                wrapper.writeCollectionFlow) == requiredGeometry &&
                geometry(manager.tlParams, manager.axiAddressWidth, manager.axiIdWidth,
                    manager.maxBurstBeats, manager.axiAddressBase, manager.axiWindowBytes,
                    manager.writeCollectionFlow) == requiredGeometry,
                "actual DDR wrapper/manager geometry differs")
            require(wrapper.maxOutstanding == expected.ddr.maxOutstanding &&
                manager.maxOutstanding == expected.ddr.maxOutstanding &&
                wrapper.maxOutstandingWrites == expected.ddr.maxOutstandingWrites &&
                manager.maxOutstandingWrites == expected.ddr.maxOutstandingWrites &&
                wrapper.unorderedResponses == expected.ddr.unorderedResponses &&
                manager.unorderedResponses == expected.ddr.unorderedResponses &&
                manager.slots.size == expected.ddr.maxOutstanding,
                "actual owner-row DDR scheduler differs from the requested profile")
            val requiredFlags = flags(expected.localPayloadWriteRow, expected.localPayloadWriteEnable,
                expected.lineReadChannel)
            require(requiredFlags == flags(expected.ddr.localPayloadWriteRow,
                expected.ddr.localPayloadWriteEnable, expected.ddr.lineReadChannel),
                "profile and DDR owner-row flags differ")
            val wrapperFlags = flags(wrapper.localPayloadWriteRow, wrapper.localPayloadWriteEnable,
                wrapper.lineReadChannel)
            val managerFlags = flags(manager.localPayloadWriteRow, manager.localPayloadWriteEnable,
                manager.lineReadChannel)
            require(wrapperFlags == requiredFlags && managerFlags == requiredFlags,
                "actual DDR wrapper/manager owner-row flags differ")
            require(wrapper.io.tl.a.bits.source.getWidth == 5 && manager.io.tl.a.bits.source.getWidth == 5 &&
                wrapper.io.tl.a.bits.size.getWidth == 3 && manager.io.tl.a.bits.size.getWidth == 3 &&
                wrapper.io.tl.d.bits.sink.getWidth == 1 && manager.io.tl.d.bits.sink.getWidth == 1 &&
                wrapper.io.axi.ar.bits.id.getWidth == 4 && manager.io.axi.ar.bits.id.getWidth == 4 &&
                wrapper.io.lineRead.nonEmpty == expected.lineReadChannel &&
                manager.io.lineRead.nonEmpty == expected.lineReadChannel,
                "actual DDR wrapper/manager ports differ")
            val slots = manager.slots.map { slot =>
                require(geometry(slot.tlParams, slot.axiAddressWidth, slot.axiIdWidth,
                    slot.maxBurstBeats, slot.axiAddressBase, slot.axiWindowBytes,
                    slot.writeCollectionFlow) == requiredGeometry, "actual DDR slot geometry differs")
                val actual = flags(slot.localPayloadWriteRow, slot.localPayloadWriteEnable, slot.lineReadChannel)
                require(actual == requiredFlags, "actual DDR physical slot owner-row flags differ")
                require(slot.io.tl.a.bits.source.getWidth == 5 && slot.io.tl.a.bits.size.getWidth == 3 &&
                    slot.io.tl.d.bits.sink.getWidth == 1 && slot.io.axi.ar.bits.id.getWidth == 4 &&
                    slot.io.lineMode.nonEmpty == expected.lineReadChannel &&
                    slot.io.lineData.map(_.getWidth) == (if (expected.lineReadChannel) Some(512) else None) &&
                    slot.payloadBanks.size == (if (expected.lineReadChannel) 8 else 0),
                    "actual DDR slot ports or payload-bank count differ")
                actual
            }
            Map("schema" -> "actual-owner-row-v1",
                "sharedCanonicalStoreOwnerMatch" -> backend.shareCanonicalStoreOwnerMatch,
                "canonicalVirtualStoreOverlap" -> backend.p.canonicalVirtualStoreOverlap,
                "wrapper" -> wrapperFlags, "manager" -> managerFlags,
                "slotCount" -> manager.slots.size, "slots" -> slots)
        }

        def write(actual: Map[String, Any], directory: String): Unit = {
            def json(value: Any): String = value match {
                case text: String => "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
                case value: Boolean => value.toString
                case value: Int => value.toString
                case fields: collection.Map[_, _] => fields.toSeq.sortBy(_._1.toString)
                    .map { case (key, item) => json(key.toString) + ":" + json(item) }.mkString("{", ",", "}")
                case items: Seq[_] => items.map(json).mkString("[", ",", "]")
                case _ => throw new IllegalArgumentException("unsupported actual owner-row value")
            }
            Files.createDirectories(Paths.get(directory))
            Files.writeString(Paths.get(directory, "actual-owner-row.json"), json(actual) + "\n")
        }
    }

    object EagerPrefixActualAudit {
        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            val core = platform.core.core.core
            val packet = core.fetchPacket.getOrElse(
                throw new IllegalArgumentException("actual registered fetch packet is absent"))
            require(core.p == expected.coreParams)
            require(packet.eagerPrefixSelect == core.p.eagerFetchPrefixSelect &&
                packet.eagerPrefixSelect == expected.eagerFetchPrefixSelect,
                "actual selected packet eager prefix flag differs")
            require(packet.alignedPermissionStage == core.p.alignedFetchPermissionStage)
            require(!packet.eagerPrefixSelect || packet.alignedPermissionStage)
            Map("schema" -> "actual-eager-prefix-v1",
                "eagerFetchPrefixSelect" -> core.p.eagerFetchPrefixSelect,
                "alignedPermissionStage" -> packet.alignedPermissionStage,
                "selectedPacketEagerPrefixSelect" -> packet.eagerPrefixSelect)
        }
        def write(actual: Map[String, Any], directory: String): Unit = {
            def json(value: Any): String = value match {
                case text: String => "\"" + text + "\""
                case value: Boolean => value.toString
                case _ => throw new IllegalArgumentException("unsupported eager prefix audit value")
            }
            val text = actual.toSeq.sortBy(_._1).map { case (key, value) => json(key) + ":" + json(value) }
                .mkString("{", ",", "}\n")
            Files.writeString(Paths.get(directory, "actual-eager-prefix.json"), text)
        }
    }

    object FutureHomeActualAudit {
        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            val home = platform.finalHome.getOrElse(
                throw new IllegalArgumentException("actual final Home absent")) match {
                case mixed: MixedCoherentLineHome => mixed
                case _ => throw new IllegalArgumentException("actual final Home must be bounded mixed")
            }
            require(home.futureWayReservation == expected.futureHomeWayReservation &&
                home.futureWayReservation == expected.cache.futureHomeWayReservation,
                "actual final Home future reservation forwarding differs")
            require(home.memoryScheduleOverlap == expected.memoryScheduleOverlap,
                "actual final Home overlap forwarding differs")
            Map("schema" -> "actual-future-home-way-v1",
                "futureHomeWayReservation" -> home.futureWayReservation,
                "memoryScheduleOverlap" -> home.memoryScheduleOverlap,
                "homeClass" -> home.getClass.getName)
        }
    }

    object HeadDrainActualAudit {
        def requireShape(c: FpgaNextConfig): Unit = {
            VersionedShapeChecks.requireShape(c)
            require(c.residentMemoryPayloadReuse == c.coreParams.residentMemoryPayloadReuse,
                "profile resident memory payload reuse was not forwarded to the core")
            require(c.postedYoungerLoadSealDeferral == c.coreParams.postedYoungerLoadSealDeferral,
                "profile younger-load seal deferral was not forwarded to the core")
            require(c.retirementIntent == c.coreParams.retirementIntent,
                "profile retirement-intent flag was not forwarded to the core")
            require(c.predecodedHeadDrain == c.coreParams.predecodedHeadDrain,
                "profile head-drain flag was not forwarded to the core")
        }

        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            requireShape(expected)
            val core = platform.core.core.core
            val backend = core.backend
            require(core.p == expected.coreParams && backend.p == core.p,
                "actual head-drain core differs from the complete requested profile")
            val rows = backend.headDrainClasses
            require(rows.nonEmpty == expected.predecodedHeadDrain,
                "actual head-drain row presence differs from the requested flag")
            rows.foreach { classes =>
                require(classes.size == core.p.robEntries && classes.forall(_.getWidth == 1),
                    "actual head-drain rows must contain one bit per ROB entry")
            }
            Map("schema" -> "actual-head-drain-v1", "predecodedHeadDrain" -> core.p.predecodedHeadDrain,
                "headDrainClassesPresent" -> rows.nonEmpty, "headDrainRows" -> rows.map(_.size).getOrElse(0),
                "headDrainRowBits" -> (if (rows.nonEmpty) 1 else 0),
                "headDrainTotalBits" -> rows.map(_.size).getOrElse(0), "robEntries" -> core.p.robEntries,
                "coreFields" -> core.p.productArity, "profileFields" -> expected.productArity)
        }

        def write(actual: Map[String, Any], directory: String): Unit = {
            Files.createDirectories(Paths.get(directory))
            Files.writeString(Paths.get(directory, "actual-head-drain.json"), PostedBoardConfiguration.json(actual) + "\n")
        }
    }

    object RetirementIntentActualAudit {
        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            HeadDrainActualAudit.requireShape(expected)
            val core = platform.core.core.core
            val b = core.backend
            require(core.p == expected.coreParams && b.p == core.p)
            require(b.p.retirementIntent == expected.retirementIntent)
            val offers = b.executionRetirementOffer
            val port = b.ledger.io.retirementIntentValid
            require(offers.nonEmpty == expected.retirementIntent && port.nonEmpty == expected.retirementIntent)
            require(offers.forall(v => v.size == 2 && v.getWidth == 2) &&
                port.forall(v => v.size == 2 && v.getWidth == 2))
            require(!expected.retirementIntent || (b.p.registeredIssueExecute && b.p.parallelCompletionPayload &&
                b.p.tagBits == 64 && b.executionStages.size == 2))
            Map("schema" -> "actual-retirement-intent-v1", "retirementIntent" -> b.p.retirementIntent,
                "rawOfferPresent" -> offers.nonEmpty, "rawOfferBits" -> offers.map(_.getWidth).getOrElse(0),
                "ledgerIntentPresent" -> port.nonEmpty, "ledgerIntentBits" -> port.map(_.getWidth).getOrElse(0),
                "registeredExecutionLanes" -> b.executionStages.size, "tagBits" -> b.p.tagBits,
                "predecodedHeadDrain" -> b.p.predecodedHeadDrain,
                "headDrainClassesPresent" -> b.headDrainClasses.nonEmpty,
                "coreFields" -> b.p.productArity, "profileFields" -> expected.productArity)
        }
    }

    object PlacedTimingActualAudit {
        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            VersionedShapeChecks.requireShape(expected)
            require(platform.core.core.core.p == expected.coreParams,
                "actual core differs from the complete placed-timing profile")
            val frontend = platform.frontend
            val fetchAdapter = platform.fetchAdapter.getOrElse(
                throw new IllegalArgumentException("actual instruction translation adapter absent"))
            val expectedFetchParams = expected.coreParams.copy(machineSystem = true,
                virtualMemoryLevels = 3, pmpEntries = 16)
            require(fetchAdapter.p == expectedFetchParams,
                "actual complete fetch-adapter params differ from the expected three platform overrides")
            require(fetchAdapter.p.fetchReadyDataClear == expected.fetchReadyDataClear,
                "actual fetch adapter did not receive ready-only data initialization")
            val adapter = platform.core.observationTranslation.getOrElse(
                throw new IllegalArgumentException("actual data translation adapter was not constructed"))
            val hint = adapter.nextLineAuthorizationInstance.getOrElse(
                throw new IllegalArgumentException("actual next-line authorization was not constructed"))
            val cache = platform.privateCache.get match {
                case c: NonBlockingCoherentLineCache => c
                case _ => throw new IllegalArgumentException("actual private cache is not the nonblocking implementation")
            }
            val wrapper = platform.ddrManagerInstance.getOrElse(
                throw new IllegalArgumentException("actual external DDR manager was not constructed"))
            val manager = wrapper.outstandingInstance.getOrElse(
                throw new IllegalArgumentException("actual outstanding DDR manager was not constructed"))
            require(frontend.fetchAddressBeforePmp == expected.fetchAddressBeforePmp,
                "actual frontend address stage differs from the requested flag")
            require(adapter.queuedHeadSelection == expected.queuedHeadSelection &&
                adapter.alignedNextLinePmp == expected.alignedNextLinePmp,
                "actual adapter local selections differ from the requested flags")
            require(hint.alignedLinePmp == expected.alignedNextLinePmp &&
                hint.checker.alignedLineAccess == expected.alignedNextLinePmp,
                "actual hint module or nested PMP checker did not receive the aligned-line flag")
            val backend = platform.core.core.core.backend
            require(backend.retirementSlotIdentity == expected.retirementSlotIdentity &&
                backend.ledger.retirementSlotIdentity == expected.retirementSlotIdentity &&
                backend.ledger.p == expected.coreParams,
                "actual backend and ledger retirement-slot parameters differ")
            require(cache.localReadSelection == expected.localCacheReadSelection,
                "actual private cache did not receive localized read selection")
            require(cache.registerProbeLookup == expected.registerProbeLookup,
                "actual nonblocking cache did not receive the registered probe flag")
            require(wrapper.localAddressRanges == expected.localAddressRanges &&
                manager.localAddressRanges == expected.localAddressRanges &&
                manager.slots.size == expected.ddr.maxOutstanding &&
                manager.slots.forall(_.localAddressRanges == expected.localAddressRanges),
                "actual DDR wrapper, manager, or burst slot did not receive the local-range flag")
            Map("schema" -> "actual-placed-timing-v1", "scope" -> "actual-constructor-only",
                "frontendClass" -> frontend.getClass.getName,
                "fetchAddressBeforePmp" -> frontend.fetchAddressBeforePmp,
                "fetchReadyDataClear" -> fetchAdapter.p.fetchReadyDataClear,
                "retirementSlotIdentityBackend" -> backend.retirementSlotIdentity,
                "retirementSlotIdentityLedger" -> backend.ledger.retirementSlotIdentity,
                "localCacheReadSelection" -> cache.localReadSelection,
                "adapterClass" -> adapter.getClass.getName, "queuedHeadSelection" -> adapter.queuedHeadSelection,
                "alignedNextLinePmp" -> adapter.alignedNextLinePmp,
                "hintClass" -> hint.getClass.getName, "hintAlignedLinePmp" -> hint.alignedLinePmp,
                "checkerClass" -> hint.checker.getClass.getName,
                "checkerAlignedLineAccess" -> hint.checker.alignedLineAccess,
                "cacheClass" -> cache.getClass.getName, "registerProbeLookup" -> cache.registerProbeLookup,
                "wrapperClass" -> wrapper.getClass.getName, "wrapperLocalAddressRanges" -> wrapper.localAddressRanges,
                "managerClass" -> manager.getClass.getName, "managerLocalAddressRanges" -> manager.localAddressRanges,
                "slotCount" -> manager.slots.size,
                "slotLocalAddressRanges" -> manager.slots.map(_.localAddressRanges),
                "headDrain" -> HeadDrainActualAudit.capture(platform, expected),
                "retirementIntent" -> RetirementIntentActualAudit.capture(platform, expected),
                "memoryPreparationLocality" -> MemoryPreparationLocalityActualAudit.capture(platform, expected),
                "nearTermA" -> NearTermAActualAudit.capture(platform, expected),
                "dynamicQualificationInherited" -> false, "physicalQualification" -> false)
        }
        def write(actual: Map[String, Any], directory: String): Unit = {
            Files.createDirectories(Paths.get(directory))
            Files.writeString(Paths.get(directory, "actual-placed-timing.json"),
                PostedBoardConfiguration.json(actual) + "\n")
        }
    }

    object MemoryPreparationLocalityActualAudit {
        def captureBackend(backend: IntegerBackend, expected: OooParams): Map[String, Any] = {
            require(backend.p == expected, "actual memory preparation backend profile differs")
            require(backend.memoryPreparationHeadOwner.nonEmpty == expected.memoryPreparationHeadMask,
                "actual memory preparation head-owner branch differs")
            require(backend.issueHeadMask.nonEmpty == expected.registeredIssueHeadMask,
                "actual registered head-mask boundary differs")
            val width = backend.memoryPreparationHeadOwner.map(_.getWidth).getOrElse(0)
            require(width == (if (expected.memoryPreparationHeadMask) expected.robEntries else 0))
            require(backend.memoryPreparationDirectSourceRanks ==
                Seq(expected.directRank0MemorySourceIds, expected.directRank1MemorySourceIds),
                "actual direct memory source-ID branches differ")
            Map("schema" -> "actual-memory-preparation-locality-v1", "scope" -> "actual-constructor-only",
                "memoryPreparationHeadMask" -> backend.memoryPreparationHeadOwner.nonEmpty,
                "headOwnerWidth" -> width, "registeredIssueHeadMask" -> backend.issueHeadMask.nonEmpty,
                "directSourceRanks" -> backend.memoryPreparationDirectSourceRanks,
                "robEntries" -> backend.p.robEntries, "physicalRegs" -> backend.p.physicalRegs,
                "tagBits" -> backend.p.tagBits, "coreFields" -> backend.p.productArity,
                "physicalQualification" -> false)
        }

        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            val core = platform.core.core.core
            require(core.p == expected.coreParams, "actual core memory preparation configuration differs")
            captureBackend(core.backend, core.p)
        }
    }

    object NearTermAActualAudit {
        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            VersionedShapeChecks.requireShape(expected)
            val core = platform.core.core.core
            val p = expected.coreParams
            require(core.p == p && core.backend.p == p, "actual complete CPU constructor differs")
            val packet = core.fetchPacket.get
            val fetch = platform.fetchAdapter.get
            val data = platform.core.observationTranslation.get
            val lsu = core.backend.lsu
            require(packet.acceptedPrefixValidation == p.fetchAcceptedPrefixValidation,
                "actual RegisteredFetchPacket did not receive accepted-prefix validation")
            require(fetch.p == p.copy(machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16) &&
                fetch.p.alignedFetchSinglePage == p.alignedFetchSinglePage,
                "actual instruction translation constructor differs")
            require(data.factorCheckedNextAllowed == p.factorCheckedNextAllowed,
                "actual DataTranslationAdapter did not receive checked hint factoring")
            require(lsu.localTaggedResponseReady == p.localTaggedResponseReady,
                "actual ParallelLoadStoreUnit did not receive local tagged readiness")
            require(lsu.slots.size == expected.lsuEntries, "actual LSU owner count changed")
            Map("schema" -> "actual-near-term-a-v1", "scope" -> "actual-constructor-only",
                "fetchAcceptedPrefixValidation" -> packet.acceptedPrefixValidation,
                "alignedFetchSinglePage" -> fetch.p.alignedFetchSinglePage,
                "factorCheckedNextAllowed" -> data.factorCheckedNextAllowed,
                "localTaggedResponseReady" -> lsu.localTaggedResponseReady,
                "coreFields" -> core.p.productArity, "profileFields" -> expected.productArity,
                "tagBits" -> p.tagBits, "lsuOwners" -> lsu.slots.size,
                "physicalMacGenericsSimulated" -> false, "physicalQualification" -> false)
        }
    }

    object HeldAluIntegrationActualAudit {
        def requireArgument(expected: FpgaNextConfig, argument: Boolean): Unit =
            require(argument == expected.coreParams.heldAluIssueForwarding,
                "held ALU argument differs from actual matching-board configuration")

        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            val core = platform.core.core.core
            val backend = core.backend
            val p = expected.coreParams
            require(core.p == p && backend.p == p && backend.ledger.p == p,
                "complete core/backend/ledger constructor parameters must be identical")
            require(backend.p.heldAluIssueForwarding == expected.heldAluIssueForwarding)
            VersionedShapeChecks.requireShape(expected)
            VersionedProfileAbi.requireLive(expected)
            VersionedProfileAbi.requireLive(core.p)
            require(backend.executionStages.size == (if (p.registeredIssueExecute) p.completionWidth else 0))
            if (p.heldAluIssueForwarding) {
                require(backend.executionStages.size == 2 && p.renameWidth == 2 && p.commitWidth == 2 &&
                    p.completionWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 &&
                    p.registeredIssueExecute && p.registeredLoadIssueForwarding && p.parallelIssuePayload &&
                    p.parallelIssueRanks && p.parallelRecoveryAdmission && !p.moveAlias &&
                    !p.loadCompletionBypass && !p.mulWordPreviewBypass)
            }
            Map("schema" -> "actual-held-alu-integration-v1", "scope" -> "actual-constructor-only",
                "core" -> core.p, "backend" -> backend.p, "ledger" -> backend.ledger.p,
                "coreNames" -> p.productElementNames.toSeq, "profileNames" -> expected.productElementNames.toSeq,
                "heldAluIssueForwarding" -> backend.p.heldAluIssueForwarding,
                "executionStages" -> backend.executionStages.size,
                "nearTermA" -> NearTermAActualAudit.capture(platform, expected),
                "profileFields" -> expected.productArity, "coreFields" -> p.productArity,
                "dynamicQualification" -> false, "physicalQualification" -> false)
        }
    }

    object ResidentMemoryIntegrationActualAudit {
        // The pinned Chisel BaseModule exposes getIds after Module construction.
        // Reflection keeps the private[chisel3] inspection API outside production code.
        private def constructedModules(backend: IntegerBackend): Seq[chisel3.experimental.BaseModule] = {
            val ids = classOf[chisel3.experimental.BaseModule].getMethod("getIds").invoke(backend)
                .asInstanceOf[scala.collection.Iterable[_]]
            ids.collect { case m: chisel3.experimental.BaseModule => m }.toSeq
        }

        def requireArgument(expected: FpgaNextConfig, argument: Boolean): Unit =
            require(argument == expected.coreParams.residentMemoryPayloadReuse,
                "resident memory argument differs from actual matching-board configuration")

        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            VersionedProfileAbi.requireLive(expected)
            VersionedShapeChecks.requireShape(expected)
            val core = platform.core.core.core
            val backend = core.backend
            val p = expected.coreParams
            require(core.p == p && backend.p == p && backend.ledger.p == p,
                "complete core/backend/ledger constructor parameters must be identical")
            require(p.productArity == 179 && expected.productArity == 96)
            require(backend.p.residentMemoryPayloadReuse == expected.residentMemoryPayloadReuse &&
                backend.residentMemoryStartAllowed.nonEmpty == p.residentMemoryPayloadReuse,
                "actual resident memory switch or start guard differs from requested constructor")
            require(backend.executionStages.size == (if (p.registeredIssueExecute) p.completionWidth else 0))
            require(backend.lsu.slots.size == p.memoryEntries)
            val modules = constructedModules(backend)
            val residentSelectors = modules.collect { case m: ResidentMemoryPreparationSelector => m }
            val descriptorSelectors = modules.collect { case m: MemoryPreparationDescriptorSelector => m }
            val ordinarySelectors = modules.collect { case m: MemoryPreparationSelector => m }
            require(backend.registeredMemoryPreparationDescriptor && p.residentMemoryPayloadReuse &&
                backend.preparationDescriptor.exists(_.getWidth == 275) &&
                backend.preparationDescriptorValid.exists(_.getWidth == 1),
                "actual registered descriptor payload/valid differs from the repair construction")
            require(residentSelectors.isEmpty && descriptorSelectors.size == 1,
                "repair must replace exactly one resident selector with one descriptor selector")
            require(ordinarySelectors.size ==
                (if (p.registeredMemoryAddress && p.parallelMemoryPreparation && !p.residentMemoryPayloadReuse) 1 else 0),
                "actual ordinary memory selector instance count differs from requested switch")
            residentSelectors.foreach { selector =>
                require(selector.io.eligible.getWidth == p.robEntries &&
                    selector.io.resident.bits.getWidth == p.robBits && selector.fresh != null,
                    "actual resident/fresh selector topology differs from core geometry")
            }
            descriptorSelectors.foreach { selector =>
                require(selector.io.eligible.getWidth == p.robEntries &&
                    selector.io.headMask.getWidth == p.robEntries &&
                    selector.io.resident.bits.getWidth == p.robBits &&
                    selector.io.descriptor.bits.getWidth == p.robBits && selector.fresh != null,
                    "actual descriptor/fresh selector topology differs from core geometry")
            }
            if (p.residentMemoryPayloadReuse) {
                require(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 &&
                    p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2 && p.memoryEntries == 4 &&
                    p.registeredMemoryAddress && p.parallelMemoryPreparation && p.parallelMemoryPayload &&
                    p.compactMemoryOperandSelect && p.parallelMemoryAddressSum && p.lvtPhysicalRegisterFile &&
                    p.ownerLocalOperandReady && p.registeredIssueExecute && !p.moveAlias &&
                    !p.loadCompletionBypass && !p.mulWordPreviewBypass && !p.memoryProofFrontier &&
                    !p.fastBufferedStoreRetire && !p.fastHeadLoadRetire)
                require(backend.executionStages.size == 2 && backend.stagedMemoryValid.nonEmpty &&
                    backend.stagedMemoryIndex.nonEmpty && backend.stagedMemoryToken.nonEmpty &&
                    backend.stagedMemoryAddress.nonEmpty && backend.stagedMemoryData.nonEmpty &&
                    backend.stagedMemorySize.nonEmpty)
            }
            Map("schema" -> "actual-resident-memory-integration-repair-r1-v1", "scope" -> "actual-constructor-only",
                "residentMemoryPayloadReuse" -> backend.p.residentMemoryPayloadReuse,
                "residentMemoryStartAllowed" -> backend.residentMemoryStartAllowed.nonEmpty,
                "residentSelectorCount" -> residentSelectors.size,
                "ordinarySelectorCount" -> ordinarySelectors.size,
                "residentSelectorClasses" -> residentSelectors.map(_.getClass.getName),
                "descriptorSelectorCount" -> descriptorSelectors.size,
                "descriptorSelectorClasses" -> descriptorSelectors.map(_.getClass.getName),
                "core" -> core.p, "backend" -> backend.p, "ledger" -> backend.ledger.p,
                "coreNames" -> core.p.productElementNames.toSeq,
                "profileNames" -> expected.productElementNames.toSeq,
                "coreFields" -> core.p.productArity, "profileFields" -> expected.productArity,
                "executionStages" -> backend.executionStages.size, "memoryEntries" -> backend.lsu.slots.size,
                "dynamicQualification" -> false, "physicalQualification" -> false)
        }
    }

    object TimingClosureActualAudit {
        private def fields(instance: AnyRef): Seq[java.lang.reflect.Field] = {
            val result = scala.collection.mutable.ArrayBuffer.empty[java.lang.reflect.Field]
            var declaring: Class[_] = instance.getClass
            while (declaring != null) {
                result ++= declaring.getDeclaredFields.filter(f => !java.lang.reflect.Modifier.isStatic(f.getModifiers))
                declaring = declaring.getSuperclass
            }
            result.toSeq
        }
        private def params(instance: AnyRef): OooParams = {
            val found = fields(instance).filter(_.getType == classOf[OooParams])
            require(found.size == 1, "actual constructor OooParams absent/ambiguous: " + instance.getClass.getName)
            found.head.setAccessible(true)
            found.head.get(instance).asInstanceOf[OooParams]
        }
        private def checkedRegister(adapter: DataTranslationAdapter): Boolean = {
            val found = fields(adapter).filter(_.getName == "registerCheckedRequests")
            require(found.size == 1 && found.head.getType == java.lang.Boolean.TYPE)
            found.head.setAccessible(true)
            found.head.getBoolean(adapter)
        }
        private def modules(backend: IntegerBackend): Seq[chisel3.experimental.BaseModule] = {
            val ids = classOf[chisel3.experimental.BaseModule].getMethod("getIds").invoke(backend)
                .asInstanceOf[scala.collection.Iterable[_]]
            ids.collect { case m: chisel3.experimental.BaseModule => m }.toSeq
        }
        def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
            VersionedProfileAbi.requireLive(expected)
            VersionedShapeChecks.requireShape(expected)
            val core = platform.core.core.core
            val backend = core.backend
            val p = expected.coreParams
            require(p.productArity == 179 && expected.productArity == 96)
            require(expected.registeredLoadResultReady == p.registeredLoadResultReady &&
                expected.frozenStoreCheckedFlow == p.frozenStoreCheckedFlow)
            require(core.p == p && backend.p == p && backend.ledger.p == p)
            val lsu = backend.lsu
            require(params(lsu) == p && lsu.slots.size == 4 && lsu.slots.forall(params(_) == p))
            val owner = backend.ownerReady.getOrElse(throw new IllegalArgumentException("owner mirror absent"))
            require(params(owner) == p && owner.ready1.size == 16 && owner.ready2.size == 16)
            val allocation = modules(backend).collect { case m: FaultAwareAllocationReady => m }
            require(allocation.size == 1 && allocation.forall(params(_) == p))
            val enabled = p.registeredLoadResultReady
            require(backend.heldLoadDestinations.nonEmpty == enabled &&
                lsu.io.loadResultPublish.nonEmpty == enabled && lsu.io.heldLoadValue.nonEmpty == enabled &&
                lsu.slots.forall(_.io.successfulLoadResultCapture.nonEmpty == enabled))
            require(owner.io.executionClass.nonEmpty == enabled && owner.io.allocationExecutionClass.nonEmpty == enabled &&
                owner.io.heldLoads.nonEmpty == enabled && owner.io.publishedLoads.nonEmpty == enabled)
            allocation.foreach { a =>
                require(a.io.allocationExecutionClass.nonEmpty == enabled && a.io.heldLoads.nonEmpty == enabled &&
                    a.io.publishedLoads.nonEmpty == enabled)
            }
            lsu.io.loadResultPublish.foreach { slots =>
                require(slots.size == 4 && slots.forall(_.bits.getWidth == p.physBits))
            }
            lsu.io.heldLoadValue.foreach { slots =>
                require(slots.size == 4 && slots.forall(x => x.bits.destination.getWidth == p.physBits &&
                    x.bits.data.getWidth == 64))
            }
            val adapter = platform.core.observationTranslation.getOrElse(
                throw new IllegalArgumentException("actual data translation adapter absent"))
            require(params(adapter) == p && checkedRegister(adapter) && adapter.registerCanonicalStoreEvent &&
                adapter.queuedHeadSelection == expected.queuedHeadSelection,
                "actual complete adapter/checked/canonical constructor differs")
            require(p.registeredCanonicalStoreEvent && p.registeredTranslationHeads &&
                p.canonicalVirtualStoreOverlap && p.pendingVirtualStoreProof && p.frozenStoreProofTransport)
            Map("schema" -> "actual-timing-closure-v1", "scope" -> "actual-constructor-only",
                "coreFields" -> p.productArity, "profileFields" -> expected.productArity,
                "registeredLoadResultReady" -> params(lsu).registeredLoadResultReady,
                "frozenStoreCheckedFlow" -> params(adapter).frozenStoreCheckedFlow,
                "core" -> core.p, "backend" -> backend.p, "ledger" -> backend.ledger.p,
                "lsu" -> params(lsu), "lsuSlots" -> lsu.slots.map(params),
                "ownerReady" -> params(owner), "allocationReady" -> allocation.map(params),
                "translation" -> params(adapter), "ownerReadyRows" -> owner.ready1.size,
                "allocationReadyInstances" -> allocation.size,
                "loadPublishSlots" -> lsu.io.loadResultPublish.map(_.size).getOrElse(0),
                "heldValueSlots" -> lsu.io.heldLoadValue.map(_.size).getOrElse(0),
                "successfulLoadCaptureSlots" -> lsu.slots.count(_.io.successfulLoadResultCapture.nonEmpty),
                "ownerExecutionClassInputs" -> owner.io.executionClass.map(_.size).getOrElse(0),
                "allocationExecutionClassInputs" -> owner.io.allocationExecutionClass.map(_.size).getOrElse(0),
                "checkedRequestsRegistered" -> checkedRegister(adapter),
                "canonicalEventRegistered" -> adapter.registerCanonicalStoreEvent,
                "queuedHeadSelection" -> adapter.queuedHeadSelection,
                "dynamicQualification" -> false, "physicalQualification" -> false)
        }
    }
}
