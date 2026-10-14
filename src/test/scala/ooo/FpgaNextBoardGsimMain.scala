package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.FpgaNextConfig

/** Shared by the CLI emitter and the actual ON/OFF elaboration test. */
object FpgaNextBoardGsim {
    def build(c: FpgaNextConfig, lineageProbes: Boolean = false, verifyConfiguration: Boolean = false): BoardSocGsim = new BoardSocGsim(
        externalDdr = true, clockHz = c.cpuHz, timingProfile = c.timingProfile,
        uartBaud = c.uartBaud, dataCacheWays = c.cacheWays, issueWidth = c.issueWidth,
        instructionPrefetch = c.instructionPrefetch, isaProfile = c.isaProfile,
        ddrMemoryBytes = c.ddrBytes, frontendProbes = true, backendProbes = true,
        instructionLineCacheLines = c.instructionCacheLines,
        dataCacheLines = c.dataCacheLines, ddrBridge = c.ddr, cacheConcurrency = c.cache,
        loadIssueForwarding = c.loadIssueForwarding, tagConfig = c.tags,
        identityDataFlow = c.identityDataFlow, fpgaStorage = c.storage,
        virtualRamLoadPrecheck = c.virtualRamLoadPrecheck, floatingPointResources = c.floatingPointResources,
        independentFetchPayloadCapture = c.independentFetchPayloadCapture,
        ownerLocalIssueReady = c.ownerLocalIssueReady, sharedFetchPmpRelations = c.sharedFetchPmpRelations,
        registeredPmpRegions = c.registeredPmpRegions, publishedPmpChanges = c.publishedPmpChanges,
        bankedInstructionData = c.bankedInstructionData, dmaLineTransfers = c.dmaLineTransfers,
        dmaLineYieldCycles = c.dmaLineYieldCycles, dmaLineEntries = c.dmaLineEntries,
        precheckedDataRequestFlow = c.precheckedDataRequestFlow, physicalLoadIngressFlow = c.physicalLoadIngressFlow,
        loadOrderOlderRetire = c.loadOrderOlderRetire, fetchPreviousPacket = c.fetchPreviousPacket,
        preparedStoreLookahead = c.preparedStoreLookahead, postedPreparationPriority = c.postedPreparationPriority,
        translatedResponseEmptyFlow = c.translatedResponseEmptyFlow,
        dataTranslationEntries = c.dataTranslationEntries, postedStoreMerge = c.postedStoreMerge,
        postedPrefetchHeadOffer = c.postedPrefetchHeadOffer,
        postedYoungerLoadSealDeferral = c.postedYoungerLoadSealDeferral,
        canonicalVirtualStoreOverlap = c.canonicalVirtualStoreOverlap, memoryProofFrontier = c.memoryProofFrontier,
        frozenStoreProofTransport = c.frozenStoreProofTransport, pendingVirtualStoreProof = c.pendingVirtualStoreProof,
        registeredPendingStoreQuery = c.registeredPendingStoreQuery,
        alignedFetchPermissionStage = c.alignedFetchPermissionStage,
        sharedLane1OwnerMatch = c.sharedLane1OwnerMatch,
        directRank1MemorySourceIds = c.directRank1MemorySourceIds,
        memoryPreparationHeadMask = c.memoryPreparationHeadMask,
        directRank0MemorySourceIds = c.directRank0MemorySourceIds,
        fetchReadyDataClear = c.fetchReadyDataClear,
        retirementSlotIdentity = c.retirementSlotIdentity, localCacheReadSelection = c.localCacheReadSelection,
        fetchAcceptedPrefixValidation = c.fetchAcceptedPrefixValidation,
        alignedFetchSinglePage = c.alignedFetchSinglePage,
        factorCheckedNextAllowed = c.factorCheckedNextAllowed,
        localTaggedResponseReady = c.localTaggedResponseReady,
        heldAluIssueForwarding = c.heldAluIssueForwarding,
        residentMemoryPayloadReuse = c.residentMemoryPayloadReuse,
        registeredLoadResultReady = c.registeredLoadResultReady,
        frozenStoreCheckedFlow = c.frozenStoreCheckedFlow,
        directRegisteredExecutionOperands = c.directRegisteredExecutionOperands,
        sharedCanonicalStoreOwnerMatch = c.sharedCanonicalStoreOwnerMatch,
        eagerFetchPrefixSelect = c.eagerFetchPrefixSelect,
        predecodedHeadDrain = c.predecodedHeadDrain,
        retirementIntent = c.retirementIntent,
        fetchAddressBeforePmp = c.fetchAddressBeforePmp,
        queuedHeadSelection = c.queuedHeadSelection, alignedNextLinePmp = c.alignedNextLinePmp,
        registerProbeLookup = c.registerProbeLookup, localAddressRanges = c.localAddressRanges,
        registeredCanonicalStoreEvent = c.registeredCanonicalStoreEvent,
        pendingVirtualStoreProofSlots = c.pendingVirtualStoreProofSlots,
        pendingStoreEarlyLoadCredits = c.pendingStoreEarlyLoadCredits, boundHeadStoreOverlap = c.boundHeadStoreOverlap,
        pendingReadyStoreBypass = c.pendingReadyStoreBypass, taggedStoreReturns = c.taggedStoreReturns, backendCapacity = c.backendCapacity,
        lineTransferDispatchFlow = c.lineTransferDispatchFlow,
        dataTlbWriteReadReuse = c.dataTlbWriteReadReuse,
        translationHitFlow = c.translationHitFlow,
        lineageProfile = if (lineageProbes) Some(c) else None,
        configurationCheck = if (verifyConfiguration) Some(c) else None)
}

/** Same fixed CPU/cache/fabric profile as the native export, without clock-domain peripherals. */
object FpgaNextBoardGsimMain extends App {
    require(args.nonEmpty, "supply an output directory and exact native export options")
    FpgaNextProfileOptions.validate(args.drop(1).toSeq)
    val options = args.drop(1).toSet
    val c = FpgaNextConfig.fromOptions(options, defaultSelected = false)
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true),
        Array("--target-dir", args(0)))
}
