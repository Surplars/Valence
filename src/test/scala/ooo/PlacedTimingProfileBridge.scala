package ooo

import soc.core.ooo._

/** Explicit append-only bridge from published 9937714 products. Field names and
  * order are fixed here; projection is allowed only for the named false fields.
  * This is source/configuration compatibility, not inherited dynamic qualification.
  */
object PlacedTimingProfileBridge {
    val publishedProfileNames: Seq[String] = Seq(
        "virtualRamLoadPrecheck", "optimized", "independentFetchPayloadCapture", "experimentalTriSpeedEthernet",
        "ownerLocalIssueReady", "sharedFetchPmpRelations", "shareProtectedHeadPayload", "bankedInstructionData",
        "prefetchCandidateCycles", "prefetchBreakOnStore", "storeNextLinePrefetch", "storePrefetchMruInsertion",
        "dmaLineTransfers", "dmaLineYieldCycles", "dmaLineEntries", "precheckedDataRequestFlow",
        "physicalLoadIngressFlow", "translatedResponseEmptyFlow", "lsuEntries", "loadOrderOlderRetire",
        "fetchPreviousPacket", "preparedStoreLookahead", "dataTranslationEntries", "postedStoreMerge",
        "postedPrefetchCoexistence", "postedPrefetchHeadOffer", "canonicalVirtualStoreOverlap", "memoryProofFrontier",
        "frozenStoreProofTransport", "pendingVirtualStoreProof", "pendingVirtualStoreProofSlots", "pendingStoreEarlyLoadCredits",
        "boundHeadStoreOverlap", "pendingReadyStoreBypass", "taggedStoreReturns", "robEntries",
        "physicalRegs", "storePrefetchLruVictim", "postedPreparationPriority", "reconstructIssueTokenIndex",
        "sharedMemoryAddressState", "distinctWayRelease", "ddrWriteCollectionFlow", "lineTransferDispatchFlow",
        "lineReadChannel", "localPayloadWriteEnable", "ddrOutstanding", "ddrWriteCredits",
        "dataTlbWriteReadReuse", "translationHitFlow", "independentDemandAdmission", "splitPrefetchTracking",
        "readPrefetchDirtyRetry", "readPrefetchDemandAdoption", "registeredPmpRegions", "publishedPmpChanges",
        "readPrefetchStoreHold", "durableReadPrefetchCandidate", "readPrefetchBehindStore", "internalLineGrant",
        "concurrentReadStorePrefetch", "memoryScheduleOverlap", "registeredPendingStoreQuery", "alignedFetchPermissionStage",
        "registeredCanonicalStoreEvent", "sharedLane1OwnerMatch", "directRank1MemorySourceIds", "directRegisteredExecutionOperands",
        "sharedCanonicalStoreOwnerMatch", "localPayloadWriteRow", "eagerFetchPrefixSelect", "futureHomeWayReservation",
        "predecodedHeadDrain", "retirementIntent")
    val publishedCoreNames: Seq[String] = Seq(
        "renameWidth", "commitWidth", "completionWidth", "robEntries",
        "physicalRegs", "tagBits", "speculativeRamBase", "speculativeRamBytes",
        "memoryEntries", "branchPredictorEntries", "bufferedRamStores", "registeredLocalStoreResponses",
        "registeredImsicInterrupts", "registeredMemoryRequests", "taggedStoreReturns", "registeredStoreResponseOwners",
        "registeredBranchRedirect", "registeredMemoryAddress", "registeredRobRetirement", "registeredLoadReplay",
        "loadOrderOlderRetire", "parallelRenameAdmission", "stableFetchFaultMetadata", "precompleteMispredictedBranch",
        "earlyRankedOperands", "pcDerivedReturnLinks", "earlyRenameDestinations", "parallelPrfReadyUpdates",
        "stablePredictionMetadata", "balancedBranchCompare", "separateBranchRetireFault", "parallelReturnStackControl",
        "earlyRedirectCapture", "parallelMemoryPreparation", "alignedFetchPmp", "parallelIssuePayload",
        "rawFetchPresence", "oneHotPhysicalOperands", "registeredTranslatedResponses", "translatedResponseEmptyFlow",
        "directMemoryResponse", "parallelFetchAddresses", "prefixTileLinkDecode", "rawTileLinkResponseMetadata",
        "bufferedRomReplies", "parallelPredictionQualification", "parallelRecoveryAdmission", "parallelRedirectTokens",
        "parallelIssueRanks", "parallelAluResults", "parallelCompletionPayload", "parallelFetchTagLookup",
        "parallelFrontendControl", "parallelAuipcQualification", "parallelPredictionSources", "parallelAddressSums",
        "bufferedFetchRequests", "parallelFetchAlignment", "parallelDecodeLegality", "flowThroughFetchRequests",
        "parallelMinMaxResults", "parallelBitLegality", "parallelRenameRanks", "parallelMinMaxWordResults",
        "parallelArchitecturalDestinations", "parallelAluWordResults", "independentFetchCapture", "parallelHomeQualification",
        "registeredFabricBoundary", "registeredTranslationHeads", "fetchReplyTurnover", "fetchIdentityTranslation",
        "registeredPredictionTraining", "parallelMemoryPayload", "parallelPacketPmp", "registeredIssueExecute",
        "registeredFetchPacket", "wordSpanPacketPmp", "parallelFetchValidation", "fetchHintEntries",
        "balancedPacketPmp", "compactMemoryOperandSelect", "parallelMemoryAddressSum", "capturedFetchPermission",
        "alignedFetchPermissionStage", "splitFetchCursor", "registeredFetchWindow", "fastHeadTrapRecovery",
        "fastHeadSystemRecovery", "tentativeRenameSources", "sharedPhysicalSourceDecode", "ownerLocalOperandReady",
        "earlyStorePreparation", "parallelMulDivDispatch", "registeredMulDivOperands", "registeredIssueHeadMask",
        "unconditionalMemoryPayloadCapture", "earlyRecoveryIssueBlock", "fastBufferedStoreRetire", "fastHeadLoadRetire",
        "loadCompletionBypass", "registeredLoadIssueForwarding", "mulWordPreviewBypass", "moveAlias",
        "flowTileLinkResponse", "storeBufferEntries", "machineSystem", "experimentalFloatingPoint",
        "floatingPoint", "advertiseFloatingPoint", "atomicMemory", "pmpEntries",
        "virtualMemoryLevels", "compressedInstructions", "instructionCacheSets", "returnStackEntries",
        "indirectTargetEntries", "recoveryWidth", "identityDataRequestFlow", "precheckedDataRequestFlow",
        "physicalLoadIngressFlow", "bankedRobPayload", "sharedStoreOperandReads", "lvtPhysicalRegisterFile",
        "dataNextLinePrefetch", "dataStoreNextLinePrefetch", "virtualRamLoadPrecheck", "bankedIssuePayload",
        "bankedFetchHints", "independentFetchPayloadCapture", "ownerLocalIssueReady", "sharedFetchPmpRelations",
        "shareProtectedHeadPayload", "fetchPreviousPacket", "preparedStoreLookahead", "postedStoreMerge",
        "postedPrefetchHeadOffer", "canonicalVirtualStoreOverlap", "memoryProofFrontier", "frozenStoreProofTransport",
        "pendingVirtualStoreProof", "pendingVirtualStoreProofSlots", "pendingStoreEarlyLoadCredits", "boundHeadStoreOverlap",
        "pendingReadyStoreBypass", "memoryProofRows", "memoryProofCacheSets", "postedPreparationPriority",
        "reconstructIssueTokenIndex", "sharedMemoryAddressState", "registeredPmpRegions", "publishedPmpChanges",
        "registeredPendingStoreQuery", "registeredCanonicalStoreEvent", "sharedLane1OwnerMatch", "directRank1MemorySourceIds",
        "directRegisteredExecutionOperands", "sharedCanonicalStoreOwnerMatch", "eagerFetchPrefixSelect", "predecodedHeadDrain",
        "retirementIntent")
    val cacheNames: Seq[String] = Seq(
        "readMshrs", "responseEntries", "writebackEntries", "overlapWritebackRefill",
        "nextLinePrefetch", "prefetchCandidateCycles", "prefetchBreakOnStore", "storeNextLinePrefetch",
        "storePrefetchMruInsertion", "postedPrefetchCoexistence", "storePrefetchLruVictim", "distinctWayRelease",
        "independentDemandAdmission", "splitPrefetchTracking", "readPrefetchDirtyRetry", "readPrefetchDemandAdoption",
        "readPrefetchStoreHold", "durableReadPrefetchCandidate", "readPrefetchBehindStore", "internalLineGrant",
        "concurrentReadStorePrefetch", "memoryScheduleOverlap", "futureHomeWayReservation")
    val ddrNames: Seq[String] = Seq(
        "maxOutstanding", "maxBurstBeats", "axiIdWidth", "maxOutstandingWrites",
        "unorderedResponses", "writeCollectionFlow", "lineReadChannel", "localPayloadWriteEnable",
        "localPayloadWriteRow")
    private val profileAdditionsBeforeYoungerLoadSeal = Seq("fetchAddressBeforePmp", "queuedHeadSelection", "alignedNextLinePmp",
        "registerProbeLookup", "localAddressRanges", "memoryPreparationHeadMask", "directRank0MemorySourceIds",
        "fetchReadyDataClear", "retirementSlotIdentity", "localCacheReadSelection",
        "fetchAcceptedPrefixValidation", "alignedFetchSinglePage", "factorCheckedNextAllowed", "localTaggedResponseReady")
    private val coreAdditionsBeforeYoungerLoadSeal = Seq("fetchAddressBeforePmp", "queuedHeadSelection", "alignedNextLinePmp",
        "memoryPreparationHeadMask", "directRank0MemorySourceIds", "fetchReadyDataClear", "retirementSlotIdentity",
        "fetchAcceptedPrefixValidation", "alignedFetchSinglePage", "factorCheckedNextAllowed", "localTaggedResponseReady")
    val platformAdditions = Seq("triSpeedRawClockHandoff")
    val youngerLoadSealField = "postedYoungerLoadSealDeferral"
    val heldAluField = "heldAluIssueForwarding"
    val residentMemoryField = "residentMemoryPayloadReuse"
    def literalFalse(value: Any): Boolean = value match {
        case b: Boolean => !b
        case _ => false
    }
    val historicalAProfileNames = publishedProfileNames ++ profileAdditionsBeforeYoungerLoadSeal
    val historicalACoreNames = publishedCoreNames ++ coreAdditionsBeforeYoungerLoadSeal
    val profileAdditions = (profileAdditionsBeforeYoungerLoadSeal ++ platformAdditions) :+ youngerLoadSealField :+ heldAluField :+ residentMemoryField
    val coreAdditions = coreAdditionsBeforeYoungerLoadSeal :+ youngerLoadSealField :+ heldAluField :+ residentMemoryField
    private def names(p: Product): Seq[String] = p.productElementNames.toSeq
    private def requireNames(p: Product, expected: Seq[String]): Unit =
        require(names(p) == expected, "complete product field names/order changed")
    def requireShape(c: FpgaNextConfig): Unit = {
        requireNames(c, publishedProfileNames ++ profileAdditions)
        requireNames(c.coreParams, publishedCoreNames ++ coreAdditions)
        requireNames(c.cache, cacheNames)
        requireNames(c.ddr, ddrNames)
    }
    /** Published A's 88/172-field view; every named appended switch must be false. */
    def historicalAFields(p: Product): Map[String, Any] = {
        val old = p match {
            case _: FpgaNextConfig => historicalAProfileNames
            case _: OooParams => historicalACoreNames
            case _ => throw new IllegalArgumentException("only exact profile/core products may be projected")
        }
        val tail = p match {
            case _: FpgaNextConfig => platformAdditions :+ youngerLoadSealField :+ heldAluField :+ residentMemoryField
            case _: OooParams => Seq(youngerLoadSealField, heldAluField, residentMemoryField)
        }
        requireNames(p, old ++ tail)
        val values = p.productElementNames.zip(p.productIterator).toMap
        require(tail.forall(n => literalFalse(values(n))), "historical A projection requires all named appended fields false")
        old.map(n => n -> values(n)).toMap
    }
    def publishedFields(p: Product): Map[String, Any] = {
        val (old, added) = p match {
            case _: FpgaNextConfig => (publishedProfileNames, profileAdditions)
            case _: OooParams => (publishedCoreNames, coreAdditions)
            case _ => throw new IllegalArgumentException("only named profile/core products may be projected")
        }
        requireNames(p, old ++ added)
        val values = p.productElementNames.zip(p.productIterator).toMap
        require(added.forall(n => literalFalse(values(n))), "only explicit default-false additions may be projected")
        old.map(n => n -> values(n)).toMap
    }
    def headDrainSnapshotFields(p: Product): Map[String, Any] = {
        val values = publishedFields(p)
        require(literalFalse(values("retirementIntent")), "snapshot predates default-false retirement intent")
        values - "retirementIntent"
    }
}
