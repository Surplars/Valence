package ooo

import soc.core.ooo.{FpgaNextConfig, FpgaNextSocTop}
import soc.ip.debug.JtagDebugParams

object CombinedTimingR1Profile {
    val identity = "combined-timing-r1"
    private val baseline = FpgaNextConfig(
        virtualRamLoadPrecheck = true,
        optimized = true,
        independentFetchPayloadCapture = true,
        experimentalTriSpeedEthernet = true,
        ownerLocalIssueReady = true,
        sharedFetchPmpRelations = true,
        shareProtectedHeadPayload = true,
        bankedInstructionData = true,
        prefetchCandidateCycles = 16,
        prefetchBreakOnStore = false,
        storeNextLinePrefetch = true,
        storePrefetchMruInsertion = true,
        dmaLineTransfers = true,
        dmaLineYieldCycles = 0,
        dmaLineEntries = 4,
        precheckedDataRequestFlow = false,
        physicalLoadIngressFlow = true,
        translatedResponseEmptyFlow = false,
        lsuEntries = 4,
        loadOrderOlderRetire = true,
        fetchPreviousPacket = true,
        preparedStoreLookahead = true,
        dataTranslationEntries = 16,
        postedStoreMerge = true,
        postedPrefetchCoexistence = true,
        postedPrefetchHeadOffer = true,
        canonicalVirtualStoreOverlap = true,
        memoryProofFrontier = false,
        frozenStoreProofTransport = true,
        pendingVirtualStoreProof = true,
        pendingVirtualStoreProofSlots = 3,
        pendingStoreEarlyLoadCredits = 2,
        boundHeadStoreOverlap = true,
        pendingReadyStoreBypass = true,
        taggedStoreReturns = true,
        robEntries = None,
        physicalRegs = None,
        storePrefetchLruVictim = true,
        postedPreparationPriority = false,
        reconstructIssueTokenIndex = false,
        sharedMemoryAddressState = true,
        distinctWayRelease = false,
        ddrWriteCollectionFlow = true,
        lineTransferDispatchFlow = true,
        lineReadChannel = true,
        localPayloadWriteEnable = true,
        ddrOutstanding = 4,
        ddrWriteCredits = 2,
        dataTlbWriteReadReuse = true,
        translationHitFlow = true,
        independentDemandAdmission = true,
        splitPrefetchTracking = true,
        readPrefetchDirtyRetry = true,
        readPrefetchDemandAdoption = true,
        registeredPmpRegions = true,
        publishedPmpChanges = true,
        readPrefetchStoreHold = true,
        durableReadPrefetchCandidate = true,
        readPrefetchBehindStore = true,
        internalLineGrant = true,
        concurrentReadStorePrefetch = true,
        memoryScheduleOverlap = true,
        registeredPendingStoreQuery = true,
        alignedFetchPermissionStage = true,
        registeredCanonicalStoreEvent = true,
        sharedLane1OwnerMatch = true,
        directRank1MemorySourceIds = true,
        directRegisteredExecutionOperands = true,
        sharedCanonicalStoreOwnerMatch = true,
        localPayloadWriteRow = true,
        eagerFetchPrefixSelect = false,
        futureHomeWayReservation = true,
        predecodedHeadDrain = true,
        retirementIntent = true,
        fetchAddressBeforePmp = true,
        queuedHeadSelection = true,
        alignedNextLinePmp = true,
        registerProbeLookup = true,
        localAddressRanges = true,
        memoryPreparationHeadMask = true,
        directRank0MemorySourceIds = true,
        fetchReadyDataClear = true,
        retirementSlotIdentity = true,
        localCacheReadSelection = true,
        fetchAcceptedPrefixValidation = true,
        alignedFetchSinglePage = true,
        factorCheckedNextAllowed = true,
        localTaggedResponseReady = true,
        triSpeedRawClockHandoff = true,
        postedYoungerLoadSealDeferral = true,
        heldAluIssueForwarding = true,
        residentMemoryPayloadReuse = true,
        registeredLoadResultReady = true,
        frozenStoreCheckedFlow = false,
        pendingReadyStoreQuery = true,
        registeredHomeRequestBoundary = false
    )
    def config(enabled: Boolean): FpgaNextConfig = {
        val c = baseline.copy(registeredHomeRequestBoundary = enabled)
        require(c.productArity == 96 && c.coreParams.productArity == 179)
        c
    }

    val debug = JtagDebugParams(
        enabled = false,
        externalDmi = false,
        addressBits = 7,
        idcode = BigInt(1),
        idleHint = 7
    )
    val bscanChain = 2

    def construct(enabled: Boolean): FpgaNextSocTop = new FpgaNextSocTop(
        config = config(enabled), debug = debug, bscanChain = bscanChain,
        preselectRedirectTokenMatches = false,
        sharedTwoWordFetchPmp = true, disjointEvictionStoreOverlap = true,
        projectedRequestHead = enabled, factorPreparedStorePool = enabled,
        proofBankControlDecoupling = enabled
    )
}
