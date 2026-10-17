// Candidate-only explicit native configuration. Compilation/export require root GO.
// Every profile argument is explicit; native boundary choices are explicit below.
// The future native audit must compare the full values/types/order with board-export-config.json.
package ooo

import soc.core.ooo.{FpgaNextConfig, FpgaNextSocTop}
import soc.ip.debug.JtagDebugParams

object CollectionReadProfileV2 {
    val identity = "qualified77-three-proof-rows-two-credits-native-r1"
    val config = FpgaNextConfig(
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
        registeredHomeRequestBoundary = true
    )
    require(config.productArity == 96 && config.coreParams.productArity == 180)
    require(config.pendingVirtualStoreProofSlots == 3 && config.coreParams.pendingVirtualStoreProofSlots == 3)
    require(config.pendingStoreEarlyLoadCredits == 2 && config.coreParams.memoryEntries == 4)
    require(config.pendingReadyStoreQuery && config.experimentalTriSpeedEthernet && config.triSpeedRawClockHandoff)

    val debug = JtagDebugParams(
        enabled = false,
        externalDmi = false,
        addressBits = 7,
        idcode = BigInt(1),
        idleHint = 7
    )
    val bscanChain = 2

    // Call only from a future separately reviewed and authorized Chisel emitter.
    // That emitter must audit the actual constructed instances before claiming equivalence.
    def construct(): FpgaNextSocTop = new FpgaNextSocTop(
        config = config, debug = debug, bscanChain = bscanChain
    )
}

// Outer physical wrapper remains soc_top_fpga_next_ddr. Its two DEFAULT-ZERO generics
// must be explicitly consumed by the retained native-MAC synthesis contract as:
// NATIVE_MAC_LOCAL_PAD_RESET_RELEASE=1, NATIVE_MAC_REGISTER_SELECTED_HALF=1.
// This sketch does not perform or authorize that synthesis.
