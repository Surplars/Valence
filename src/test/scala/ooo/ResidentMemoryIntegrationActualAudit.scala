package ooo

import soc.core.ooo._

/** Reads the real constructed instances. No hardware ports, state or taps are added. */
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
        ProfileAbi77.requireLive(expected)
        PlacedTimingProfileBridge.requireShape(expected)
        val core = platform.core.core.core
        val backend = core.backend
        val p = expected.coreParams
        require(core.p == p && backend.p == p && backend.ledger.p == p,
            "complete core/backend/ledger constructor parameters must be identical")
        require(p.productArity == 178 && expected.productArity == 95)
        require(backend.p.residentMemoryPayloadReuse == expected.residentMemoryPayloadReuse &&
            backend.residentMemoryStartAllowed.nonEmpty == p.residentMemoryPayloadReuse,
            "actual resident memory switch or start guard differs from requested constructor")
        require(backend.executionStages.size == (if (p.registeredIssueExecute) p.completionWidth else 0))
        require(backend.lsu.slots.size == p.memoryEntries)
        val modules = constructedModules(backend)
        val residentSelectors = modules.collect { case m: ResidentMemoryPreparationSelector => m }
        val ordinarySelectors = modules.collect { case m: MemoryPreparationSelector => m }
        require(residentSelectors.size == (if (p.residentMemoryPayloadReuse) 1 else 0),
            "actual resident selector instance count differs from requested switch")
        require(ordinarySelectors.size ==
            (if (p.registeredMemoryAddress && p.parallelMemoryPreparation && !p.residentMemoryPayloadReuse) 1 else 0),
            "actual ordinary memory selector instance count differs from requested switch")
        residentSelectors.foreach { selector =>
            require(selector.io.eligible.getWidth == p.robEntries &&
                selector.io.resident.bits.getWidth == p.robBits && selector.fresh != null,
                "actual resident/fresh selector topology differs from core geometry")
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
        Map("schema" -> "actual-resident-memory-integration-v1", "scope" -> "actual-constructor-only",
            "residentMemoryPayloadReuse" -> backend.p.residentMemoryPayloadReuse,
            "residentMemoryStartAllowed" -> backend.residentMemoryStartAllowed.nonEmpty,
            "residentSelectorCount" -> residentSelectors.size,
            "ordinarySelectorCount" -> ordinarySelectors.size,
            "residentSelectorClasses" -> residentSelectors.map(_.getClass.getName),
            "core" -> core.p, "backend" -> backend.p, "ledger" -> backend.ledger.p,
            "coreNames" -> core.p.productElementNames.toSeq,
            "profileNames" -> expected.productElementNames.toSeq,
            "coreFields" -> core.p.productArity, "profileFields" -> expected.productArity,
            "executionStages" -> backend.executionStages.size, "memoryEntries" -> backend.lsu.slots.size,
            "dynamicQualification" -> false, "physicalQualification" -> false)
    }
}
