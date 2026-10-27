package soc.core.ooo

import soc.ip.dma.NetworkDmaConfig

/** Versioned geometry for the independent FPGA-first integration. Explicit optional
  * backend capacity experiments preserve every omitted dimension.
  * Historical BoardSocConfig defaults deliberately remain unchanged. Replacements
  * are selected separately from dimensions so an area/throughput comparison cannot
  * silently gain capacity, remove RV64GC, or disable a protection mechanism.
  */
final case class FpgaNextConfig(
    virtualRamLoadPrecheck: Boolean = false,
    optimized: Boolean = false,
    independentFetchPayloadCapture: Boolean = false,
    experimentalTriSpeedEthernet: Boolean = false,
    ownerLocalIssueReady: Boolean = false,
    sharedFetchPmpRelations: Boolean = false,
    shareProtectedHeadPayload: Boolean = false,
    bankedInstructionData: Boolean = false,
    prefetchCandidateCycles: Int = 1,
    prefetchBreakOnStore: Boolean = false,
    storeNextLinePrefetch: Boolean = false,
    storePrefetchMruInsertion: Boolean = false,
    dmaLineTransfers: Boolean = false,
    dmaLineYieldCycles: Int = 0,
    dmaLineEntries: Int = 1,
    precheckedDataRequestFlow: Boolean = false,
    physicalLoadIngressFlow: Boolean = false,
    translatedResponseEmptyFlow: Boolean = false,
    lsuEntries: Int = 2,
    loadOrderOlderRetire: Boolean = false,
    fetchPreviousPacket: Boolean = false,
    preparedStoreLookahead: Boolean = false,
    dataTranslationEntries: Int = 8,
    postedStoreMerge: Boolean = false,
    postedPrefetchCoexistence: Boolean = false,
    postedPrefetchHeadOffer: Boolean = false,
    canonicalVirtualStoreOverlap: Boolean = false,
    memoryProofFrontier: Boolean = false,
    frozenStoreProofTransport: Boolean = false,
    pendingVirtualStoreProof: Boolean = false,
    pendingVirtualStoreProofSlots: Int = 1,
    pendingStoreEarlyLoadCredits: Int = 1,
    boundHeadStoreOverlap: Boolean = false,
    pendingReadyStoreBypass: Boolean = false,
    taggedStoreReturns: Boolean = false,
    robEntries: Option[Int] = None,
    physicalRegs: Option[Int] = None,
    storePrefetchLruVictim: Boolean = false,
    postedPreparationPriority: Boolean = false,
    reconstructIssueTokenIndex: Boolean = false,
    sharedMemoryAddressState: Boolean = false,
    distinctWayRelease: Boolean = false,
    ddrWriteCollectionFlow: Boolean = false,
    lineTransferDispatchFlow: Boolean = false,
    lineReadChannel: Boolean = false,
    localPayloadWriteEnable: Boolean = false,
    ddrOutstanding: Int = 4,
    ddrWriteCredits: Int = 2,
    dataTlbWriteReadReuse: Boolean = false,
    translationHitFlow: Boolean = false,
    independentDemandAdmission: Boolean = false,
    splitPrefetchTracking: Boolean = false,
    readPrefetchDirtyRetry: Boolean = false,
    readPrefetchDemandAdoption: Boolean = false,
    registeredPmpRegions: Boolean = false,
    publishedPmpChanges: Boolean = false,
    readPrefetchStoreHold: Boolean = false,
    durableReadPrefetchCandidate: Boolean = false,
    readPrefetchBehindStore: Boolean = false,
    internalLineGrant: Boolean = false,
    concurrentReadStorePrefetch: Boolean = false,
    memoryScheduleOverlap: Boolean = false,
    registeredPendingStoreQuery: Boolean = false,
    alignedFetchPermissionStage: Boolean = false,
    registeredCanonicalStoreEvent: Boolean = false,
    sharedLane1OwnerMatch: Boolean = false,
    directRank1MemorySourceIds: Boolean = false,
    directRegisteredExecutionOperands: Boolean = false,
    sharedCanonicalStoreOwnerMatch: Boolean = false,
    localPayloadWriteRow: Boolean = false,
    eagerFetchPrefixSelect: Boolean = false,
    futureHomeWayReservation: Boolean = false,
    predecodedHeadDrain: Boolean = false,
    retirementIntent: Boolean = false,
    fetchAddressBeforePmp: Boolean = false,
    queuedHeadSelection: Boolean = false,
    alignedNextLinePmp: Boolean = false,
    registerProbeLookup: Boolean = false,
    localAddressRanges: Boolean = false,
    memoryPreparationHeadMask: Boolean = false,
    directRank0MemorySourceIds: Boolean = false,
    fetchReadyDataClear: Boolean = false,
    retirementSlotIdentity: Boolean = false,
    localCacheReadSelection: Boolean = false,
    fetchAcceptedPrefixValidation: Boolean = false,
    alignedFetchSinglePage: Boolean = false,
    factorCheckedNextAllowed: Boolean = false,
    localTaggedResponseReady: Boolean = false,
    triSpeedRawClockHandoff: Boolean = false,
    postedYoungerLoadSealDeferral: Boolean = false,
    heldAluIssueForwarding: Boolean = false,
    residentMemoryPayloadReuse: Boolean = false,
    registeredLoadResultReady: Boolean = false,
    frozenStoreCheckedFlow: Boolean = false,
    pendingReadyStoreQuery: Boolean = false,
    registeredHomeRequestBoundary: Boolean = false,
    // Explicit Common-A1 rebuild topology; legacy board factories must not silently ignore it.
    completionTopology: String = "legacy",
    branchResolutionTopology: String = "writeback-coupled",
    fetchTransactionSlots: Int = 1,
    registeredDataTranslation: Boolean = false,
    circularFetchPayload: Boolean = false,
    completedCanonicalStoreForwarding: Boolean = false,
    combinedCheckedDataFlow: Boolean = false,
    preparedHeadStoreOperands: Boolean = false,
    elasticLoadProofSupply: Boolean = false,
    registeredRawCertifiedFlow: Boolean = false,
    factoredDataPmpRange: Boolean = false,
    guardedNaturalDataPmp: Boolean = false,
    // Combinational counted tag advance only; no new stage, state or allocation credit.
    splitLowTagAdvance: Boolean = false,
    bufferedThirdRankLoadProof: Boolean = false,
    // Named two-slot empty-return flow plus slot-derived issue token identity experiment.
    bufferedReturnFlow: Boolean = false,
    // Integer ordered-owner readiness only; generic/tagged/FP LSU semantics stay unchanged.
    orderedLsuResponseReady: Boolean = false,
    // Registered advisory exclusion changes only the third source1 preparation supplier.
    registeredAdvisoryExclusion: Boolean = false,
    // Explicit candidate only; never infer ingress flow from a certified request flag.
    certifiedLoadIngress: Boolean = false,
    // Default-off, explicitly selected Common-A1 frontend experiment.
    fetchThirdPacketLookahead: Boolean = false,
    // Explicit efficiency-refactor capabilities; old/public profiles keep all disabled.
    canonicalFetchCacheKeys: Boolean = false,
    registeredMemoryOperandCapture: Boolean = false,
    sharedMulDivOperandReads: Boolean = false,
    sourceLocalLoadProofCancellation: Boolean = false,
    sharedLoadProofPmpBounds: Boolean = false,
    decodedNaturalPmp: Boolean = false,
    preparedBareHeadStoreOperands: Boolean = false,
    bankedRobCompletionData: Boolean = false,
    coexistingPhysicalLoadIngress: Boolean = false,
    // None preserves the exact selected topology; this is not a new public default.
    branchPredictorEntriesOverride: Option[Int] = None
) {
    require(!coexistingPhysicalLoadIngress || (bankedRobCompletionData && certifiedLoadIngress &&
        !physicalLoadIngressFlow && !registeredDataTranslation && !registeredRawCertifiedFlow),
        "coexisting physical ingress belongs only to the explicit third-efficiency descendant")
    require(!bankedRobCompletionData || (decodedNaturalPmp && preparedBareHeadStoreOperands &&
        completionTopology == "dual-owner" &&
        robEntries.forall(_ == 16) && physicalRegs.forall(_ == 48)),
        "banked ROB completion data belongs only to the explicit second-efficiency descendant")
    require(branchPredictorEntriesOverride.forall(n => n >= 2 && n <= 256 && (n & (n - 1)) == 0),
        "branch predictor override must be a power of two in [2, 256]")
    require(branchPredictorEntriesOverride.isEmpty || fetchThirdPacketLookahead,
        "branch predictor overrides belong to explicit Common-A1 experiments")
    require(!canonicalFetchCacheKeys || fetchThirdPacketLookahead,
        "canonical fetch keys require the explicit identity-horizon frontend")
    require(!registeredMemoryOperandCapture || bufferedThirdRankLoadProof,
        "numerical memory capture requires the buffered proof profile")
    require(!sharedMulDivOperandReads || fetchThirdPacketLookahead,
        "shared M operand reads are an explicit Common-A1 efficiency candidate")
    require(!sourceLocalLoadProofCancellation || bufferedThirdRankLoadProof,
        "source-local proof cancellation requires the buffered proof profile")
    require(!sharedLoadProofPmpBounds || bufferedThirdRankLoadProof,
        "shared proof PMP bounds require the buffered proof profile")
    require(!decodedNaturalPmp || (guardedNaturalDataPmp && bufferedThirdRankLoadProof &&
        sharedLoadProofPmpBounds && sourceLocalLoadProofCancellation && fetchThirdPacketLookahead),
        "typed natural PMP belongs to the explicit first-batch descendant")
    require(!preparedBareHeadStoreOperands || (preparedHeadStoreOperands && registeredMemoryOperandCapture &&
        canonicalVirtualStoreOverlap && lsuEntries == 4 && robEntries.forall(_ == 16) &&
        physicalRegs.forall(_ == 48) && completionTopology == "dual-owner" &&
        !postedStoreMerge && !postedPrefetchHeadOffer && !postedPrefetchCoexistence &&
        !memoryProofFrontier && !residentMemoryPayloadReuse && !pendingVirtualStoreProof && !preparedStoreLookahead),
        "prepared bare head-store operands belong to the explicit ordinary four-owner A1 experiment")
    require(!fetchThirdPacketLookahead || (certifiedLoadIngress && fetchTransactionSlots == 2 &&
        alignedFetchSinglePage && !alignedFetchPermissionStage && !fetchAddressBeforePmp && !fetchPreviousPacket),
        "identity fetch horizon requires the complete certified-ingress two-owner frontend")
    require(!registeredAdvisoryExclusion || (orderedLsuResponseReady && bufferedThirdRankLoadProof),
        "registered advisory exclusion requires the named ordered-owner buffered preparation topology")
    require(!orderedLsuResponseReady || (bufferedReturnFlow && lsuEntries == 4 &&
        robEntries.forall(_ == 16) && physicalRegs.forall(_ == 48) && !taggedStoreReturns &&
        !registeredLoadResultReady),
        "ordered LSU readiness requires the explicit four-owner buffered-return descendant")
    require(!bufferedReturnFlow || (guardedNaturalDataPmp && splitLowTagAdvance && bufferedThirdRankLoadProof &&
        translatedResponseEmptyFlow && reconstructIssueTokenIndex && !registeredLoadResultReady),
        "buffered return flow requires the explicit buffered proof, empty-return and slot-index combination")
    require(!bufferedThirdRankLoadProof || (guardedNaturalDataPmp && splitLowTagAdvance &&
        !registeredLoadResultReady),
        "buffered third-rank proof is a distinct guarded split-tag descendant")
    require(!guardedNaturalDataPmp || (elasticLoadProofSupply && combinedCheckedDataFlow &&
        !registeredDataTranslation && !registeredRawCertifiedFlow && !factoredDataPmpRange &&
        !physicalLoadIngressFlow && (!translatedResponseEmptyFlow || bufferedReturnFlow) && !queuedHeadSelection &&
        !postedStoreMerge && !taggedStoreReturns && !pendingVirtualStoreProof && !memoryProofFrontier &&
        !frozenStoreProofTransport && !frozenStoreCheckedFlow && !registeredCanonicalStoreEvent),
        "guarded natural data PMP retains the explicit elastic topology and rejects malformed raw requests")
    require(!factoredDataPmpRange || (elasticLoadProofSupply && combinedCheckedDataFlow &&
        !registeredDataTranslation && !registeredRawCertifiedFlow),
        "factored data PMP ranges use only the explicit elastic demand-hit profile")
    require(!registeredRawCertifiedFlow || (registeredDataTranslation && precheckedDataRequestFlow &&
        !translationHitFlow && !combinedCheckedDataFlow && virtualRamLoadPrecheck &&
        canonicalVirtualStoreOverlap && !queuedHeadSelection && !physicalLoadIngressFlow &&
        !translatedResponseEmptyFlow && !postedStoreMerge && !taggedStoreReturns &&
        !pendingVirtualStoreProof && !memoryProofFrontier && !frozenStoreProofTransport &&
        !frozenStoreCheckedFlow && !registeredCanonicalStoreEvent),
        "registered raw/certified flow explicitly separates demand lookup from checked PA authorization")
    require(!elasticLoadProofSupply || (preparedHeadStoreOperands && virtualRamLoadPrecheck &&
        lsuEntries == 4 && !residentMemoryPayloadReuse && !preparedStoreLookahead &&
        !memoryProofFrontier && !pendingVirtualStoreProof && !postedStoreMerge && !taggedStoreReturns),
        "elastic load proof supply requires the explicit ordered head-store preparation candidate")
    require(!preparedHeadStoreOperands || ((combinedCheckedDataFlow || registeredRawCertifiedFlow) &&
        completedCanonicalStoreForwarding &&
        !residentMemoryPayloadReuse && !preparedStoreLookahead),
        "prepared head-store operands require the explicit checked-flow candidate without resident shortcuts")
    require(!combinedCheckedDataFlow || (translationHitFlow && precheckedDataRequestFlow &&
        virtualRamLoadPrecheck && canonicalVirtualStoreOverlap && !registeredDataTranslation &&
        !queuedHeadSelection && !physicalLoadIngressFlow && (!translatedResponseEmptyFlow || bufferedReturnFlow) &&
        !postedStoreMerge && !taggedStoreReturns && !pendingVirtualStoreProof && !memoryProofFrontier &&
        !frozenStoreProofTransport && !frozenStoreCheckedFlow && !registeredCanonicalStoreEvent),
        "combined checked flow explicitly retains demand-hit and certified-PA paths without other shortcuts")
    require(!completedCanonicalStoreForwarding || (completionTopology == "dual-owner" &&
        virtualRamLoadPrecheck && canonicalVirtualStoreOverlap && !registeredCanonicalStoreEvent &&
        !pendingVirtualStoreProof && !taggedStoreReturns && !postedStoreMerge),
        "completed canonical forwarding requires the explicit ordered dual-owner memory profile")
    require(!registeredDataTranslation || (!translationHitFlow && !queuedHeadSelection &&
        virtualRamLoadPrecheck && canonicalVirtualStoreOverlap),
        "registered translation must explicitly replace hit flow, not silently override it")
    require(Set("legacy", "dual-owner").contains(completionTopology), "unknown completion topology")
    require(Set(1, 2).contains(fetchTransactionSlots), "common A1 fetch supports one or two explicit owners")
    require(fetchTransactionSlots == 1 || (alignedFetchSinglePage && !alignedFetchPermissionStage &&
        !fetchAddressBeforePmp && !fetchPreviousPacket),
        "two-owner fetch requires the aligned single-page path without prepared/frontier/previous-packet experiments")
    require(Set("writeback-coupled", "execution-mailbox").contains(branchResolutionTopology),
        "unknown branch resolution topology")
    require(branchResolutionTopology == "writeback-coupled" || completionTopology == "dual-owner",
        "execution-mailbox branch resolution requires explicit dual-owner completion")
    require(!pendingReadyStoreQuery || (pendingReadyStoreBypass && pendingVirtualStoreProof &&
        registeredPendingStoreQuery && memoryPreparationHeadMask &&
        Set(2, 3).contains(pendingVirtualStoreProofSlots) && pendingStoreEarlyLoadCredits == 2),
        "ready non-head query requires the bounded registered two/three-proof, two-credit profile")
    require(!triSpeedRawClockHandoff || experimentalTriSpeedEthernet,
        "RAW MAC handoff requires tri-speed Ethernet")
    val backendCapacity = BackendCapacityConfig(robEntries, physicalRegs)
    require(!postedYoungerLoadSealDeferral || (postedStoreMerge && !memoryProofFrontier),
        "younger-load seal deferral requires posted store merging without a proof frontier")
    require(!independentDemandAdmission || (virtualRamLoadPrecheck && canonicalVirtualStoreOverlap),
        "the CPU admission batch requires exact canonical virtual-store authorization")
    require(!translationHitFlow || (virtualRamLoadPrecheck &&
        (!precheckedDataRequestFlow || combinedCheckedDataFlow)),
        "simultaneous demand-hit and prechecked flow requires the explicit combined checked policy")
    SvTranslationService.indexBits(dataTranslationEntries)
    require(Set(4, 8).contains(ddrOutstanding), "FPGA-next DDR pool must be four or eight slots")
    require(Set(1, 2, 4).contains(ddrWriteCredits) && ddrWriteCredits <= ddrOutstanding,
        "FPGA-next write credits must be 1, 2 or 4 within the shared pool")
    require(!futureHomeWayReservation || memoryScheduleOverlap,
        "future Home way reservation requires memory scheduling overlap")
    require(!queuedHeadSelection || (precheckedDataRequestFlow || translationHitFlow),
        "queued head selection requires a checked translation-flow source")
    require(!fetchAddressBeforePmp || alignedFetchPermissionStage,
        "fetch address preparation requires the aligned fetch permission topology")
    require(!eagerFetchPrefixSelect || alignedFetchPermissionStage,
        "eager fetch prefix selection requires the aligned permission stage")
    require(!sharedCanonicalStoreOwnerMatch || canonicalVirtualStoreOverlap,
        "shared canonical-store owner matching requires canonical virtual-store overlap")
    require(!localPayloadWriteRow || (lineReadChannel && localPayloadWriteEnable),
        "local payload write rows require line banks and localized upper-bank enables")
    require(!registeredCanonicalStoreEvent || canonicalVirtualStoreOverlap,
        "registered canonical-store events require canonical virtual-store overlap")
    require(!registeredPendingStoreQuery || pendingVirtualStoreProof,
        "registered pending-store queries require pending-store proofs")
    require(!pendingReadyStoreBypass || boundHeadStoreOverlap,
        "ready pending-store bypass requires bound head-store overlap")
    require(!boundHeadStoreOverlap || pendingVirtualStoreProof,
        "bound head-store overlap requires the independent pending-store proof profile")
    require(Set(1, 2, 3).contains(pendingVirtualStoreProofSlots),
        "pending virtual-store proofs use one, two or three bounded slots")
    require(pendingVirtualStoreProofSlots != 3 || (pendingReadyStoreQuery &&
        pendingStoreEarlyLoadCredits == 2),
        "third proof row is isolated to the registered ready-query profile with two early-load credits")
    require(Set(1, 2).contains(pendingStoreEarlyLoadCredits), "pending-store early loads use one or two credits")
    require(pendingStoreEarlyLoadCredits == 1 || pendingVirtualStoreProof,
        "additional early-load responsibility requires pending-store proofs")
    require(!frozenStoreProofTransport || (virtualRamLoadPrecheck && canonicalVirtualStoreOverlap),
        "frozen-store transport requires canonical virtual-store origins")
    require(!pendingVirtualStoreProof || (!memoryProofFrontier && frozenStoreProofTransport &&
        robEntries.getOrElse(16) == 16 && physicalRegs.getOrElse(48) == 48 && lsuEntries == 4 &&
        virtualRamLoadPrecheck && canonicalVirtualStoreOverlap && loadOrderOlderRetire && dataTranslationEntries == 16),
        "pending virtual-store proofs require the separate ROB16/PRF48/LSU4/DTLB16 staged profile")
    require(!memoryProofFrontier || (robEntries.contains(64) && physicalRegs.contains(64) && lsuEntries == 4 &&
        virtualRamLoadPrecheck && canonicalVirtualStoreOverlap && loadOrderOlderRetire && dataTranslationEntries == 16),
        "memory proof frontier requires the explicitly selected reviewed capacity and translation profile")
    require(!canonicalVirtualStoreOverlap || virtualRamLoadPrecheck,
        "canonical virtual store overlap requires explicit virtual RAM load precheck")
    require(!postedPreparationPriority || (preparedStoreLookahead && postedStoreMerge),
        "posted preparation priority requires prepared store lookahead and posted store merging")
    require(!postedPrefetchHeadOffer || (postedStoreMerge && postedPrefetchCoexistence),
        "posted PF head offer requires posted store merging and cache PF coexistence")
    require(!postedPrefetchCoexistence || postedStoreMerge,
        "posted/prefetch coexistence requires posted store merging")
    require(!postedStoreMerge || !precheckedDataRequestFlow,
        "posted store candidate excludes unqualified prechecked data empty-flow")
    require(!storePrefetchMruInsertion || storeNextLinePrefetch,
        "store-origin MRU insertion requires checked store prefetch")
    require(!storePrefetchLruVictim || storeNextLinePrefetch,
        "store-origin LRU victim selection requires checked store prefetch")
    require(!readPrefetchDemandAdoption || (splitPrefetchTracking && independentDemandAdmission),
        "read prefetch demand adoption requires split tracking and independent demand admission")
    require(!readPrefetchStoreHold || prefetchCandidateCycles > 1,
        "read prefetch store hold requires an existing multi-cycle candidate")
    require(!readPrefetchDirtyRetry || splitPrefetchTracking,
        "read prefetch dirty retry requires split prefetch tracking")
    require(!splitPrefetchTracking || storeNextLinePrefetch,
        "split prefetch tracking requires checked store prefetch")
    require(Set(2, 4).contains(lsuEntries), "FPGA-next LSU experiment uses two or four owners")
    require(Set(1, 2, 4, 8).contains(dmaLineEntries) && (dmaLineTransfers || dmaLineEntries == 1))
    require(Set(0, 4, 8, 16, 32, 64).contains(dmaLineYieldCycles) && (dmaLineTransfers || dmaLineYieldCycles == 0))
    require(!precheckedDataRequestFlow || virtualRamLoadPrecheck,
        "prechecked flow is an explicit virtual-load-precheck experiment")
    val selectedTopology = optimized && independentFetchPayloadCapture && ownerLocalIssueReady &&
        sharedFetchPmpRelations && shareProtectedHeadPayload && bankedInstructionData
    val name = (if (selectedTopology) "fpga-next-selected-v2" else if (optimized)
        "fpga-next-storage-v1" else "fpga-next-reference-topology-v1") +
        (if (fetchTransactionSlots != 1) s"-fetch-owners$fetchTransactionSlots" else "") +
        (if (completionTopology != "legacy") s"-completion-$completionTopology" else "") +
        (if (branchResolutionTopology != "writeback-coupled") s"-branch-$branchResolutionTopology" else "") +
        (if (!selectedTopology && independentFetchPayloadCapture) "-fetch-capture" else "") +
        (if (!selectedTopology && ownerLocalIssueReady) "-owner-ready" else "") +
        (if (!selectedTopology && sharedFetchPmpRelations) "-shared-pmp" else "") +
        (if (!selectedTopology && shareProtectedHeadPayload) "-shared-head" else "") +
        (if (!selectedTopology && bankedInstructionData) "-banked-idata" else "") +
        (if (prefetchCandidateCycles > 1) s"-prefetch-retry${prefetchCandidateCycles}" else "") +
        (if (prefetchBreakOnStore) "-store-break" else "") +
        (if (virtualRamLoadPrecheck) "-virtual-precheck" else "") +
        (if (dataTranslationEntries != 8) s"-dtlb$dataTranslationEntries" else "") +
        (if (precheckedDataRequestFlow) "-prechecked-flow" else "") +
        (if (combinedCheckedDataFlow) "-combined-checked-flow" else "") +
        (if (preparedHeadStoreOperands) "-prepared-head-store" else "") +
        (if (elasticLoadProofSupply) "-elastic-load-proof" else "") +
        (if (registeredRawCertifiedFlow) "-registered-raw-certified-flow" else "") +
        (if (factoredDataPmpRange) "-factored-data-pmp-range" else "") +
        (if (guardedNaturalDataPmp) "-guarded-natural-data-pmp" else "") +
        (if (splitLowTagAdvance) "-split-low-tag-advance" else "") +
        (if (bufferedThirdRankLoadProof) "-buffered-third-rank-proof" else "") +
        (if (bufferedReturnFlow) "-buffered-return-flow" else "") +
        (if (orderedLsuResponseReady) "-ordered-owner-ready" else "") +
        (if (registeredAdvisoryExclusion) "-registered-advisory-exclusion" else "") +
        (if (certifiedLoadIngress) "-certified-load-ingress" else "") +
        (if (fetchThirdPacketLookahead) "-identity-fetch-horizon" else "") +
        branchPredictorEntriesOverride.map(n => s"-bht$n").getOrElse("") +
        (if (canonicalFetchCacheKeys) "-canonical-fetch-cache-keys" else "") +
        (if (registeredMemoryOperandCapture) "-registered-memory-operand-capture" else "") +
        (if (sharedMulDivOperandReads) "-shared-mul-div-operand-reads" else "") +
        (if (sourceLocalLoadProofCancellation) "-source-local-load-proof-cancellation" else "") +
        (if (sharedLoadProofPmpBounds) "-shared-load-proof-pmp-bounds" else "") +
        (if (decodedNaturalPmp) "-decoded-natural-pmp" else "") +
        (if (preparedBareHeadStoreOperands) "-prepared-bare-head-store" else "") +
        (if (bankedRobCompletionData) "-banked-rob-completion-data" else "") +
        (if (coexistingPhysicalLoadIngress) "-coexisting-physical-load-ingress" else "") +
        (if (physicalLoadIngressFlow) "-physical-ingress-flow" else "") +
        (if (translatedResponseEmptyFlow) "-translated-response-empty-flow" else "") +
        (if (lsuEntries != 2) s"-lsu$lsuEntries" else "") +
        robEntries.map(n => s"-rob$n").getOrElse("") +
        physicalRegs.map(n => s"-prf$n").getOrElse("") +
        (if (loadOrderOlderRetire) "-older-load-retire" else "") +
        (if (fetchPreviousPacket) "-fetch-previous-packet" else "") +
        (if (preparedStoreLookahead) "-prepared-store-lookahead" else "") +
        (if (postedPreparationPriority) "-posted-preparation-priority" else "") +
        (if (reconstructIssueTokenIndex) "-reconstruct-issue-token-index" else "") +
        (if (sharedMemoryAddressState) "-shared-memory-address-state" else "") +
        (if (storeNextLinePrefetch) "-checked-store-prefetch" else "") +
        (if (storePrefetchMruInsertion) "-store-prefetch-mru" else "") +
        (if (storePrefetchLruVictim) "-store-prefetch-lru-victim" else "") +
        (if (distinctWayRelease) "-distinct-way-release" else "") +
        (if (postedStoreMerge) "-posted-store-merge" else "") +
        (if (postedPrefetchCoexistence) "-posted-prefetch-coexistence" else "") +
        (if (postedPrefetchHeadOffer) "-posted-prefetch-head-offer" else "") +
        (if (canonicalVirtualStoreOverlap) "-canonical-virtual-store-overlap" else "") +
        (if (memoryProofFrontier) "-memory-proof-frontier" else "") +
        (if (frozenStoreProofTransport) "-frozen-store-proof-transport" else "") +
        (if (pendingVirtualStoreProof) s"-pending-virtual-store-proof$pendingVirtualStoreProofSlots" else "") +
        (if (registeredPendingStoreQuery) "-registered-pending-store-query" else "") +
        (if (alignedFetchPermissionStage) "-aligned-fetch-permission-stage" else "") +
        (if (fetchAddressBeforePmp) "-fetch-address-before-pmp" else "") +
        (if (queuedHeadSelection) "-queued-head-selection" else "") +
        (if (registeredDataTranslation) "-registered-data-translation" else "") +
        (if (circularFetchPayload) "-circular-fetch-payload" else "") +
        (if (completedCanonicalStoreForwarding) "-completed-canonical-forward" else "") +
        (if (alignedNextLinePmp) "-aligned-next-line-pmp" else "") +
        (if (registerProbeLookup) "-register-probe-lookup" else "") +
        (if (localAddressRanges) "-local-address-ranges" else "") +
        (if (sharedLane1OwnerMatch) "-shared-lane1-owner-match" else "") +
        (if (memoryPreparationHeadMask) "-memory-preparation-head-mask" else "") +
        (if (directRank0MemorySourceIds) "-direct-rank0-memory-source-ids" else "") +
        (if (fetchReadyDataClear) "-fetch-ready-data-clear" else "") +
        (if (retirementSlotIdentity) "-retirement-slot-identity" else "") +
        (if (localCacheReadSelection) "-local-cache-read-selection" else "") +
        (if (directRank1MemorySourceIds) "-direct-rank1-memory-source-ids" else "") +
        (if (directRegisteredExecutionOperands) "-direct-registered-execution-operands" else "") +
        (if (registeredCanonicalStoreEvent) "-registered-canonical-store-event" else "") +
        (if (pendingStoreEarlyLoadCredits != 1) s"-pending-store-early-load-credits$pendingStoreEarlyLoadCredits" else "") +
        (if (boundHeadStoreOverlap) "-bound-head-store-overlap" else "") +
        (if (pendingReadyStoreBypass) "-pending-ready-store-bypass" else "") +
        (if (taggedStoreReturns) "-tagged-store-returns" else "") +
        (if (experimentalTriSpeedEthernet) "-experimental-trispeed" else "") +
        (if (triSpeedRawClockHandoff) "-mac-raw-handoff" else "") +
        (if (dmaLineTransfers) "-dma-lines" else "") +
        (if (dmaLineEntries > 1) s"-owners${dmaLineEntries}" else "") +
        (if (dmaLineYieldCycles > 0) s"-yield${dmaLineYieldCycles}" else "") +
        (if (ddrWriteCollectionFlow) "-ddr-write-collection-flow" else "") +
        (if (lineTransferDispatchFlow) "-line-transfer-dispatch-flow" else "") +
        (if (lineReadChannel) "-line-read-channel" else "") +
        (if (eagerFetchPrefixSelect) "-eager-fetch-prefix-select" else "") +
        (if (sharedCanonicalStoreOwnerMatch) "-shared-canonical-store-owner-match" else "") +
        (if (localPayloadWriteRow) "-local-payload-write-row" else "") +
        (if (localPayloadWriteEnable) "-local-payload-write-enable" else "") +
        (if (ddrOutstanding != 4 || ddrWriteCredits != 2) s"-ddr${ddrOutstanding}w${ddrWriteCredits}" else "") +
        (if (dataTlbWriteReadReuse) "-dtlb-write-read-reuse" else "") +
        (if (translationHitFlow) "-translation-hit-flow" else "") +
        (if (independentDemandAdmission) "-independent-demand-admission" else "") +
        (if (splitPrefetchTracking) "-split-prefetch-tracking" else "") +
        (if (readPrefetchDirtyRetry) "-read-prefetch-dirty-retry" else "") +
        (if (readPrefetchDemandAdoption) "-read-prefetch-demand-adoption" else "") +
        (if (registeredPmpRegions) "-registered-pmp-regions" else "") +
        (if (publishedPmpChanges) "-published-pmp-changes" else "") +
        (if (readPrefetchStoreHold) "-read-prefetch-store-hold" else "") +
        (if (durableReadPrefetchCandidate) "-durable-read-prefetch-candidate" else "") +
        (if (readPrefetchBehindStore) "-read-prefetch-behind-store" else "") +
        (if (internalLineGrant) "-internal-line-grant" else "") +
        (if (concurrentReadStorePrefetch) "-concurrent-read-store-prefetch" else "") +
        (if (memoryScheduleOverlap) "-memory-schedule-overlap" else "") +
        (if (futureHomeWayReservation) "-future-home-way-reservation" else "") +
        (if (predecodedHeadDrain) "-predecoded-head-drain" else "") +
        (if (retirementIntent) "-retirement-intent" else "") +
        (if (fetchAcceptedPrefixValidation) "-fetch-accepted-prefix-validation" else "") +
        (if (alignedFetchSinglePage) "-aligned-fetch-single-page" else "") +
        (if (factorCheckedNextAllowed) "-factor-checked-next-allowed" else "") +
        (if (localTaggedResponseReady) "-local-tagged-response-ready" else "") +
        (if (postedYoungerLoadSealDeferral) "-posted-younger-load-seal-deferral" else "") +
        (if (heldAluIssueForwarding) "-held-alu-issue-forwarding" else "") +
        (if (residentMemoryPayloadReuse) "-resident-memory-payload-reuse" else "") +
        (if (registeredLoadResultReady) "-registered-load-result-ready" else "") +
        (if (frozenStoreCheckedFlow) "-frozen-store-checked-flow" else "") +
        (if (pendingReadyStoreQuery) "-pending-ready-store-query" else "")
    val interfaceVersion = 1
    val timingProfile = if (lsuEntries == 4) BoardSocConfig.memoryCapacityProfile else "staged-fetch-turnover"
    val isaProfile = "rv64gc"
    val issueWidth = 2
    // Validate only after the derived width has been initialized.
    require(!certifiedLoadIngress || (registeredAdvisoryExclusion && orderedLsuResponseReady &&
        bufferedReturnFlow && bufferedThirdRankLoadProof && splitLowTagAdvance && guardedNaturalDataPmp &&
        virtualRamLoadPrecheck && precheckedDataRequestFlow && combinedCheckedDataFlow && translationHitFlow &&
        canonicalVirtualStoreOverlap && issueWidth == 2 && lsuEntries == 4 && dataTranslationEntries == 16 &&
        robEntries.forall(_ == 16) && physicalRegs.forall(_ == 48) &&
        completionTopology == "dual-owner" && branchResolutionTopology == "execution-mailbox" &&
        circularFetchPayload && fetchTransactionSlots == 2 && alignedFetchSinglePage &&
        !physicalLoadIngressFlow && !registeredDataTranslation && !registeredRawCertifiedFlow && !factoredDataPmpRange),
        "certified load ingress requires the complete guarded-natural advisory-owner VM control")
    val cpuHz = 100000000
    val uartBaud = 460800
    val aonHz = 50000000
    val uartHz = 50000000
    val ddrUiHz = 250000000
    val ramBase: BigInt = BoardSocConfig.ramBase
    val ddrBytes: BigInt = BigInt(2) * 1024 * 1024 * 1024
    val ramEndExclusive: BigInt = ramBase + ddrBytes
    val cacheLineBytes = 64
    val instructionCacheLines = 512
    val dataCacheLines = 512
    val cacheWays = 2
    val ddr = DdrBridgeConfig(maxOutstanding = ddrOutstanding, maxBurstBeats = 16, axiIdWidth = 4,
        maxOutstandingWrites = ddrWriteCredits, unorderedResponses = true, writeCollectionFlow = ddrWriteCollectionFlow,
        lineReadChannel = lineReadChannel, localPayloadWriteEnable = localPayloadWriteEnable,
        localPayloadWriteRow = localPayloadWriteRow)
    val cache = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2,
        writebackEntries = 2, overlapWritebackRefill = true, nextLinePrefetch = true,
        prefetchCandidateCycles = prefetchCandidateCycles, prefetchBreakOnStore = prefetchBreakOnStore,
        storeNextLinePrefetch = storeNextLinePrefetch, storePrefetchMruInsertion = storePrefetchMruInsertion,
        postedPrefetchCoexistence = postedPrefetchCoexistence, storePrefetchLruVictim = storePrefetchLruVictim,
        distinctWayRelease = distinctWayRelease, independentDemandAdmission = independentDemandAdmission,
        splitPrefetchTracking = splitPrefetchTracking, readPrefetchDirtyRetry = readPrefetchDirtyRetry,
        readPrefetchDemandAdoption = readPrefetchDemandAdoption, readPrefetchStoreHold = readPrefetchStoreHold,
        durableReadPrefetchCandidate = durableReadPrefetchCandidate, readPrefetchBehindStore = readPrefetchBehindStore,
        internalLineGrant = internalLineGrant, concurrentReadStorePrefetch = concurrentReadStorePrefetch,
        memoryScheduleOverlap = memoryScheduleOverlap, futureHomeWayReservation = futureHomeWayReservation)
    val tags = CacheTagConfig(compact = true, bankedStorage = optimized)
    val floatingPointResources = if (optimized) FloatingPointResourceConfig.fpga else FloatingPointResourceConfig.baseline
    val storage = FpgaStorageConfig(bankedRobPayload = true, sharedStoreOperandReads = true,
        lvtPhysicalRegisterFile = true, bankedIssuePayload = optimized, bankedFetchHints = optimized,
        shareProtectedHeadPayload = shareProtectedHeadPayload, reconstructIssueTokenIndex = reconstructIssueTokenIndex,
        sharedMemoryAddressState = sharedMemoryAddressState)
    val network = NetworkDmaConfig(maxFrameBytes = 2048, macRxSlots = 4, postedRxSlots = 4,
        memoryCredits = 4, postedTxSlots = 4)
    val triSpeedTxFrameSlots = if (experimentalTriSpeedEthernet) 2 else 1
    val loadIssueForwarding = Some(true)
    val identityDataFlow = true
    // The registered two-word frontend already owns its instruction fetch window.
    // InstructionLineCache suppresses line prefetch in that profile.
    val instructionPrefetch = true

    def coreParams: OooParams = {
        val base = BoardSocConfig.boardParams(timingProfile, issueWidth,
        externalDdr = true, isa = isaProfile, ddrMemoryBytes = ddrBytes,
        loadIssueForwarding = loadIssueForwarding, identityDataFlow = identityDataFlow,
        fpgaStorage = storage, dataNextLinePrefetch = cache.nextLinePrefetch,
        dataStoreNextLinePrefetch = cache.storeNextLinePrefetch,
        virtualRamLoadPrecheck = virtualRamLoadPrecheck, floatingPointResources = floatingPointResources,
        independentFetchPayloadCapture = independentFetchPayloadCapture,
        ownerLocalIssueReady = ownerLocalIssueReady, sharedFetchPmpRelations = sharedFetchPmpRelations,
        registeredPmpRegions = registeredPmpRegions, publishedPmpChanges = publishedPmpChanges,
        precheckedDataRequestFlow = precheckedDataRequestFlow, physicalLoadIngressFlow = physicalLoadIngressFlow,
        translatedResponseEmptyFlow = translatedResponseEmptyFlow,
        loadOrderOlderRetire = loadOrderOlderRetire, fetchPreviousPacket = fetchPreviousPacket,
        postedPreparationPriority = postedPreparationPriority,
        preparedStoreLookahead = preparedStoreLookahead, postedStoreMerge = postedStoreMerge,
        postedPrefetchHeadOffer = postedPrefetchHeadOffer,
        postedYoungerLoadSealDeferral = postedYoungerLoadSealDeferral,
        heldAluIssueForwarding = heldAluIssueForwarding,
        residentMemoryPayloadReuse = residentMemoryPayloadReuse,
        registeredLoadResultReady = registeredLoadResultReady,
        frozenStoreCheckedFlow = frozenStoreCheckedFlow,
        pendingReadyStoreQuery = pendingReadyStoreQuery,
        registeredHomeRequestBoundary = registeredHomeRequestBoundary,
        canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap, memoryProofFrontier = memoryProofFrontier,
        frozenStoreProofTransport = frozenStoreProofTransport, pendingVirtualStoreProof = pendingVirtualStoreProof,
        registeredPendingStoreQuery = registeredPendingStoreQuery,
        alignedFetchPermissionStage = alignedFetchPermissionStage,
        sharedLane1OwnerMatch = sharedLane1OwnerMatch,
        directRank1MemorySourceIds = directRank1MemorySourceIds,
        memoryPreparationHeadMask = memoryPreparationHeadMask,
        directRank0MemorySourceIds = directRank0MemorySourceIds,
        fetchReadyDataClear = fetchReadyDataClear,
        retirementSlotIdentity = retirementSlotIdentity,
        fetchAcceptedPrefixValidation = fetchAcceptedPrefixValidation, alignedFetchSinglePage = alignedFetchSinglePage,
        factorCheckedNextAllowed = factorCheckedNextAllowed, localTaggedResponseReady = localTaggedResponseReady,
        directRegisteredExecutionOperands = directRegisteredExecutionOperands,
        sharedCanonicalStoreOwnerMatch = sharedCanonicalStoreOwnerMatch,
        eagerFetchPrefixSelect = eagerFetchPrefixSelect,
        predecodedHeadDrain = predecodedHeadDrain,
        retirementIntent = retirementIntent,
        fetchAddressBeforePmp = fetchAddressBeforePmp,
        queuedHeadSelection = queuedHeadSelection, alignedNextLinePmp = alignedNextLinePmp,
        registeredCanonicalStoreEvent = registeredCanonicalStoreEvent,
        pendingVirtualStoreProofSlots = pendingVirtualStoreProofSlots,
        pendingStoreEarlyLoadCredits = pendingStoreEarlyLoadCredits, boundHeadStoreOverlap = boundHeadStoreOverlap,
            pendingReadyStoreBypass = pendingReadyStoreBypass, taggedStoreReturns = taggedStoreReturns,
        backendCapacity = backendCapacity)
        base.copy(
            branchPredictorEntries = branchPredictorEntriesOverride.getOrElse(base.branchPredictorEntries),
            completionTopology = completionTopology,
            branchResolutionTopology = branchResolutionTopology,
            registeredDataTranslation = registeredDataTranslation, circularFetchPayload = circularFetchPayload,
            completedCanonicalStoreForwarding = completedCanonicalStoreForwarding,
            combinedCheckedDataFlow = combinedCheckedDataFlow,
            preparedHeadStoreOperands = preparedHeadStoreOperands,
            elasticLoadProofSupply = elasticLoadProofSupply,
            registeredRawCertifiedFlow = registeredRawCertifiedFlow,
            factoredDataPmpRange = factoredDataPmpRange,
            guardedNaturalDataPmp = guardedNaturalDataPmp,
            splitLowTagAdvance = splitLowTagAdvance,
            bufferedThirdRankLoadProof = bufferedThirdRankLoadProof,
            bufferedReturnFlow = bufferedReturnFlow,
            orderedLsuResponseReady = orderedLsuResponseReady,
            registeredAdvisoryExclusion = registeredAdvisoryExclusion,
            certifiedLoadIngress = certifiedLoadIngress,
            fetchThirdPacketLookahead = fetchThirdPacketLookahead,
            canonicalFetchCacheKeys = canonicalFetchCacheKeys,
            registeredMemoryOperandCapture = registeredMemoryOperandCapture,
            sharedMulDivOperandReads = sharedMulDivOperandReads,
            sourceLocalLoadProofCancellation = sourceLocalLoadProofCancellation,
            sharedLoadProofPmpBounds = sharedLoadProofPmpBounds,
            decodedNaturalPmp = decodedNaturalPmp,
            preparedBareHeadStoreOperands = preparedBareHeadStoreOperands,
            bankedRobCompletionData = bankedRobCompletionData,
            coexistingPhysicalLoadIngress = coexistingPhysicalLoadIngress)
    }

    def managedBoard(jtagRamDownload: Boolean = false, preselectRedirectTokenMatches: Boolean = false, proofBankControlDecoupling: Boolean = false, projectedRequestHead: Boolean = false, factorPreparedStorePool: Boolean = false, sharedTwoWordFetchPmp: Boolean = false, disjointEvictionStoreOverlap: Boolean = false, registerNextLineDecision: Boolean = false, registeredMemoryPreparationDescriptor: Boolean = false, backendNaturalAlignedPmp: Boolean = false, earlyLoadPreparationDescriptor: Boolean = false, dataTlbMissCacheEntries: Int = 0, virtualStoreOperandLookahead: Boolean = false, bankedStoreData: Boolean = false): BoardSocTop = {
        require(completionTopology == "legacy" && branchResolutionTopology == "writeback-coupled" &&
            fetchTransactionSlots == 1 && !registeredDataTranslation && !circularFetchPayload &&
            !completedCanonicalStoreForwarding && !combinedCheckedDataFlow && !preparedHeadStoreOperands &&
            !elasticLoadProofSupply && !registeredRawCertifiedFlow && !factoredDataPmpRange && !guardedNaturalDataPmp &&
            !splitLowTagAdvance && !bufferedThirdRankLoadProof && !bufferedReturnFlow &&
            !orderedLsuResponseReady && !registeredAdvisoryExclusion && !certifiedLoadIngress &&
            !fetchThirdPacketLookahead && !canonicalFetchCacheKeys && !registeredMemoryOperandCapture &&
            !sharedMulDivOperandReads && !sourceLocalLoadProofCancellation && !sharedLoadProofPmpBounds &&
            !decodedNaturalPmp && !preparedBareHeadStoreOperands && !bankedRobCompletionData &&
            !coexistingPhysicalLoadIngress &&
            branchPredictorEntriesOverride.isEmpty,
            "experimental backend/fetch topologies use CommonA1CpuTile, not the legacy board factory")
        new BoardSocTop(
        socClockHz = cpuHz, externalDdr = true, timingProfile = timingProfile,
        uartBaud = uartBaud, dataCacheWays = cacheWays, issueWidth = issueWidth,
        instructionPrefetch = instructionPrefetch, isaProfile = isaProfile,
        peripheralClockHz = uartHz, ethernetControl = true, ethernetDma = true,
        clockManagementHz = aonHz, ddrUiClockHz = ddrUiHz, managedPeripherals = true,
        ddrMemoryBytes = ddrBytes, instructionLineCacheLines = instructionCacheLines,
        dataCacheLines = dataCacheLines, ddrBridge = ddr, cacheConcurrency = cache,
        loadIssueForwarding = loadIssueForwarding, tagConfig = tags,
        networkDmaConfig = network, identityDataFlow = identityDataFlow,
        fpgaStorage = storage, virtualRamLoadPrecheck = virtualRamLoadPrecheck,
        floatingPointResources = floatingPointResources, independentFetchPayloadCapture = independentFetchPayloadCapture,
        triSpeedEthernet = experimentalTriSpeedEthernet, triSpeedTxFrameSlots = triSpeedTxFrameSlots,
        triSpeedRawClockHandoff = triSpeedRawClockHandoff,
        ownerLocalIssueReady = ownerLocalIssueReady, sharedFetchPmpRelations = sharedFetchPmpRelations,
        registeredPmpRegions = registeredPmpRegions, publishedPmpChanges = publishedPmpChanges,
        bankedInstructionData = bankedInstructionData, jtagRamDownload = jtagRamDownload,
        dmaLineTransfers = dmaLineTransfers, dmaLineYieldCycles = dmaLineYieldCycles, dmaLineEntries = dmaLineEntries,
        precheckedDataRequestFlow = precheckedDataRequestFlow, physicalLoadIngressFlow = physicalLoadIngressFlow,
        translatedResponseEmptyFlow = translatedResponseEmptyFlow,
        loadOrderOlderRetire = loadOrderOlderRetire, fetchPreviousPacket = fetchPreviousPacket,
        postedPreparationPriority = postedPreparationPriority,
        preparedStoreLookahead = preparedStoreLookahead,
        dataTranslationEntries = dataTranslationEntries, postedStoreMerge = postedStoreMerge,
        postedPrefetchHeadOffer = postedPrefetchHeadOffer,
        postedYoungerLoadSealDeferral = postedYoungerLoadSealDeferral,
        heldAluIssueForwarding = heldAluIssueForwarding,
        residentMemoryPayloadReuse = residentMemoryPayloadReuse,
        registeredLoadResultReady = registeredLoadResultReady,
        frozenStoreCheckedFlow = frozenStoreCheckedFlow,
        pendingReadyStoreQuery = pendingReadyStoreQuery,
        registeredHomeRequestBoundary = registeredHomeRequestBoundary,
        canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap, memoryProofFrontier = memoryProofFrontier,
        frozenStoreProofTransport = frozenStoreProofTransport, pendingVirtualStoreProof = pendingVirtualStoreProof,
        registeredPendingStoreQuery = registeredPendingStoreQuery,
        alignedFetchPermissionStage = alignedFetchPermissionStage,
        sharedLane1OwnerMatch = sharedLane1OwnerMatch,
        directRank1MemorySourceIds = directRank1MemorySourceIds,
        memoryPreparationHeadMask = memoryPreparationHeadMask,
        directRank0MemorySourceIds = directRank0MemorySourceIds,
        fetchReadyDataClear = fetchReadyDataClear,
        retirementSlotIdentity = retirementSlotIdentity,
        fetchAcceptedPrefixValidation = fetchAcceptedPrefixValidation, alignedFetchSinglePage = alignedFetchSinglePage,
        factorCheckedNextAllowed = factorCheckedNextAllowed, localTaggedResponseReady = localTaggedResponseReady,
        directRegisteredExecutionOperands = directRegisteredExecutionOperands,
        sharedCanonicalStoreOwnerMatch = sharedCanonicalStoreOwnerMatch,
        eagerFetchPrefixSelect = eagerFetchPrefixSelect,
        predecodedHeadDrain = predecodedHeadDrain,
        retirementIntent = retirementIntent,
        registerProbeLookup = registerProbeLookup, localAddressRanges = localAddressRanges,
        localCacheReadSelection = localCacheReadSelection,
        fetchAddressBeforePmp = fetchAddressBeforePmp,
        queuedHeadSelection = queuedHeadSelection, alignedNextLinePmp = alignedNextLinePmp,
        registeredCanonicalStoreEvent = registeredCanonicalStoreEvent,
        pendingVirtualStoreProofSlots = pendingVirtualStoreProofSlots,
        pendingStoreEarlyLoadCredits = pendingStoreEarlyLoadCredits, boundHeadStoreOverlap = boundHeadStoreOverlap,
            pendingReadyStoreBypass = pendingReadyStoreBypass, taggedStoreReturns = taggedStoreReturns,
        backendCapacity = backendCapacity, lineTransferDispatchFlow = lineTransferDispatchFlow,
        dataTlbWriteReadReuse = dataTlbWriteReadReuse, translationHitFlow = translationHitFlow,
        preselectRedirectTokenMatches = preselectRedirectTokenMatches,
        proofBankControlDecoupling = proofBankControlDecoupling,
        projectedRequestHead = projectedRequestHead, factorPreparedStorePool = factorPreparedStorePool,
        registeredMemoryPreparationDescriptor = registeredMemoryPreparationDescriptor, backendNaturalAlignedPmp = backendNaturalAlignedPmp,
        earlyLoadPreparationDescriptor = earlyLoadPreparationDescriptor, dataTlbMissCacheEntries = dataTlbMissCacheEntries,
        virtualStoreOperandLookahead = virtualStoreOperandLookahead,
        bankedStoreData = bankedStoreData,
        registerNextLineDecision = registerNextLineDecision,
        sharedTwoWordFetchPmp = sharedTwoWordFetchPmp,
        disjointEvictionStoreOverlap = disjointEvictionStoreOverlap)
    }
}

object FpgaNextConfig {
    val Reference = FpgaNextConfig()
    val Candidate = FpgaNextConfig(optimized = true)
    // Separately qualified timing experiment; the base candidate remains frozen.
    val FetchCaptureCandidate = Candidate.copy(independentFetchPayloadCapture = true)
    val TriSpeedCandidate = Candidate.copy(experimentalTriSpeedEthernet = true)
    val ControlCandidate = FetchCaptureCandidate.copy(ownerLocalIssueReady = true, sharedFetchPmpRelations = true)
    val Selected = ControlCandidate.copy(shareProtectedHeadPayload = true, bankedInstructionData = true)

    // Source-prepared timing candidate. Activation remains explicit and does not
    // change any frozen preset or its capacity/ISA/cache policy.
    val RegisteredPmpCandidate = Selected.copy(registeredPmpRegions = true)

    def fromOptions(options: Set[String], defaultSelected: Boolean): FpgaNextConfig = {
        for (flag <- Set("--posted-younger-load-seal-deferral", "--frozen-store-proof-transport", "--pending-virtual-store-proof",
            "--registered-pending-store-query", "--aligned-fetch-permission-stage", "--registered-canonical-store-event", "--shared-lane1-owner-match", "--direct-rank1-memory-source-ids", "--memory-preparation-head-mask", "--direct-rank0-memory-source-ids", "--direct-registered-execution-operands", "--shared-canonical-store-owner-match", "--local-payload-write-row",
            "--bound-head-store-overlap", "--pending-ready-store-bypass", "--tagged-store-returns", "--read-prefetch-store-hold",
            "--durable-read-prefetch-candidate", "--read-prefetch-behind-store",
            "--internal-line-grant", "--concurrent-read-store-prefetch", "--memory-schedule-overlap", "--future-home-way-reservation", "--predecoded-head-drain", "--retirement-intent",
            "--fetch-address-before-pmp", "--queued-head-selection", "--aligned-next-line-pmp", "--register-probe-lookup", "--local-address-ranges", "--fetch-accepted-prefix-validation", "--aligned-fetch-single-page", "--factor-checked-next-allowed", "--local-tagged-response-ready",
            "--tri-speed-raw-clock-handoff", "--held-alu-issue-forwarding", "--resident-memory-payload-reuse")) {
            require(!options.exists(_.startsWith(flag + "=")), s"$flag does not accept a value")
        }
        require(!options.exists(o => o.startsWith("--resident") && o != "--resident-memory-payload-reuse"),
            "only exact --resident-memory-payload-reuse is accepted")
        require(!options.exists(o => o.startsWith("--held-alu") && o != "--held-alu-issue-forwarding"),
            "held ALU forwarding requires the exact non-valued option")
        require(!options.exists(_.startsWith("--published-pmp-changes=")),
            "--published-pmp-changes does not accept a value")
        require(!options.exists(_.startsWith("--registered-pmp-regions=")),
            "--registered-pmp-regions does not accept a value")
        require(!options.exists(_.startsWith("--read-prefetch-demand-adoption=")),
            "--read-prefetch-demand-adoption does not accept a value")
        require(!options.exists(_.startsWith("--read-prefetch-dirty-retry=")),
            "--read-prefetch-dirty-retry does not accept a value")
        require(!options.exists(_.startsWith("--split-prefetch-tracking=")),
            "--split-prefetch-tracking does not accept a value")
        require(!options.exists(_.startsWith("--ddr-write-collection-flow=")),
            "--ddr-write-collection-flow does not accept a value")
        require(!options.exists(_.startsWith("--line-transfer-dispatch-flow=")),
            "--line-transfer-dispatch-flow does not accept a value")
        require(!options.exists(_.startsWith("--line-read-channel=")),
            "--line-read-channel does not accept a value")
        require(!options.exists(_.startsWith("--local-payload-write-enable=")),
            "--local-payload-write-enable does not accept a value")
        require(!options.exists(_.startsWith("--independent-demand-admission=")),
            "--independent-demand-admission does not accept a value")
        require(!options.exists(_.startsWith("--dtlb-write-read-reuse=")),
            "--dtlb-write-read-reuse does not accept a value")
        require(!options.exists(_.startsWith("--reconstruct-issue-token-index=")),
            "--reconstruct-issue-token-index does not accept a value")
        require(!options.exists(_.startsWith("--shared-memory-address-state=")),
            "--shared-memory-address-state does not accept a value")
        require(!options.exists(_.startsWith("--eager-fetch-prefix-select=")),
            "--eager-fetch-prefix-select does not accept a value")
        val selectors = options.intersect(Set("--reference", "--candidate", "--selected"))
        require(selectors.size <= 1, "choose one FPGA-next profile")
        val base = if (options.contains("--reference")) Reference
            else if (options.contains("--candidate")) Candidate
            else if (options.contains("--selected") || defaultSelected) Selected else Reference
        val lifetimes = options.filter(_.startsWith("--prefetch-candidate-cycles="))
        require(lifetimes.size <= 1, "choose one prefetch candidate lifetime")
        val lifetime = lifetimes.headOption.map(_.stripPrefix("--prefetch-candidate-cycles=").toInt).getOrElse(1)
        require(Set(1, 3, 16).contains(lifetime), "FPGA-next prefetch experiments use 1, 3 or 16 attempts")
        val tlbCounts = options.filter(_.startsWith("--data-translation-entries="))
        require(tlbCounts.size <= 1, "choose one data translation entry count")
        val tlbCount = tlbCounts.headOption.map(_.stripPrefix("--data-translation-entries=").toInt).getOrElse(8)
        val ownerCounts = options.filter(_.startsWith("--lsu-entries="))
        require(ownerCounts.size <= 1, "choose one LSU owner count")
        val lsuCount = ownerCounts.headOption.map(_.stripPrefix("--lsu-entries=").toInt).getOrElse(2)
        def capacityOption(prefix: String): Option[Int] = {
            val values = options.filter(_.startsWith(prefix))
            require(values.size <= 1, s"choose one $prefix capacity")
            values.headOption.map(_.stripPrefix(prefix).toInt)
        }
        val robCount = capacityOption("--rob-entries=")
        val physicalCount = capacityOption("--physical-regs=")
        val yields = options.filter(_.startsWith("--dma-line-yield-cycles="))
        require(yields.size <= 1, "choose one DMA line yield duration")
        val lineYield = yields.headOption.map(_.stripPrefix("--dma-line-yield-cycles=").toInt).getOrElse(0)
        val depths = options.filter(_.startsWith("--dma-line-entries="))
        require(depths.size <= 1, "choose one DMA line owner count")
        val lineDepth = depths.headOption.map(_.stripPrefix("--dma-line-entries=").toInt).getOrElse(1)
        val ddrSlots = capacityOption("--ddr-outstanding=").getOrElse(4)
        val ddrWrites = capacityOption("--ddr-write-credits=").getOrElse(2)
        base.copy(
            registeredPmpRegions = options.contains("--registered-pmp-regions"),
            publishedPmpChanges = options.contains("--published-pmp-changes"),
            dataTranslationEntries = tlbCount,
            postedStoreMerge = options.contains("--posted-store-merge"),
            postedYoungerLoadSealDeferral = options.contains("--posted-younger-load-seal-deferral"),
            heldAluIssueForwarding = options.contains("--held-alu-issue-forwarding"),
            residentMemoryPayloadReuse = options.contains("--resident-memory-payload-reuse"),
            registeredLoadResultReady = options.contains("--registered-load-result-ready"),
            frozenStoreCheckedFlow = options.contains("--frozen-store-checked-flow"),
            pendingReadyStoreQuery = options.contains("--pending-ready-store-query"),
            postedPrefetchCoexistence = options.contains("--posted-prefetch-coexistence"),
            postedPrefetchHeadOffer = options.contains("--posted-prefetch-head-offer"),
            canonicalVirtualStoreOverlap = options.contains("--canonical-virtual-store-overlap"),
            memoryProofFrontier = options.contains("--memory-proof-frontier"),
            frozenStoreProofTransport = options.contains("--frozen-store-proof-transport"),
            pendingVirtualStoreProof = options.contains("--pending-virtual-store-proof"),
            registeredPendingStoreQuery = options.contains("--registered-pending-store-query"),
            alignedFetchPermissionStage = options.contains("--aligned-fetch-permission-stage"),
            fetchAddressBeforePmp = options.contains("--fetch-address-before-pmp"),
            queuedHeadSelection = options.contains("--queued-head-selection"),
            alignedNextLinePmp = options.contains("--aligned-next-line-pmp"),
            registerProbeLookup = options.contains("--register-probe-lookup"),
            localAddressRanges = options.contains("--local-address-ranges"),
            sharedLane1OwnerMatch = options.contains("--shared-lane1-owner-match"),
            directRank1MemorySourceIds = options.contains("--direct-rank1-memory-source-ids"),
            memoryPreparationHeadMask = options.contains("--memory-preparation-head-mask"),
            directRank0MemorySourceIds = options.contains("--direct-rank0-memory-source-ids"),
            fetchReadyDataClear = options.contains("--fetch-ready-data-clear"),
            retirementSlotIdentity = options.contains("--retirement-slot-identity"),
            fetchAcceptedPrefixValidation = options.contains("--fetch-accepted-prefix-validation"),
            alignedFetchSinglePage = options.contains("--aligned-fetch-single-page"),
            factorCheckedNextAllowed = options.contains("--factor-checked-next-allowed"),
            localTaggedResponseReady = options.contains("--local-tagged-response-ready"),
            localCacheReadSelection = options.contains("--local-cache-read-selection"),
            directRegisteredExecutionOperands = options.contains("--direct-registered-execution-operands"),
            registeredCanonicalStoreEvent = options.contains("--registered-canonical-store-event"),
            boundHeadStoreOverlap = options.contains("--bound-head-store-overlap"),
            pendingReadyStoreBypass = options.contains("--pending-ready-store-bypass"),
            taggedStoreReturns = options.contains("--tagged-store-returns"),
            pendingVirtualStoreProofSlots = capacityOption("--pending-virtual-store-proof-slots=").getOrElse(1),
            pendingStoreEarlyLoadCredits = capacityOption("--pending-store-early-load-credits=").getOrElse(1),
            lsuEntries = lsuCount, robEntries = robCount, physicalRegs = physicalCount,
            loadOrderOlderRetire = options.contains("--load-order-older-retire"),
            fetchPreviousPacket = options.contains("--fetch-previous-packet"),
            preparedStoreLookahead = options.contains("--prepared-store-lookahead"),
            postedPreparationPriority = options.contains("--posted-preparation-priority"),
            reconstructIssueTokenIndex = options.contains("--reconstruct-issue-token-index"),
            sharedMemoryAddressState = options.contains("--shared-memory-address-state"),
            dmaLineEntries = lineDepth,
            dmaLineYieldCycles = lineYield,
            dmaLineTransfers = options.contains("--dma-line-transfers"),
            prefetchCandidateCycles = lifetime,
            precheckedDataRequestFlow = options.contains("--prechecked-data-flow"),
            physicalLoadIngressFlow = options.contains("--physical-load-ingress-flow"),
            translatedResponseEmptyFlow = options.contains("--translated-response-empty-flow"),
            prefetchBreakOnStore = options.contains("--prefetch-break-on-store"),
            storeNextLinePrefetch = options.contains("--store-next-line-prefetch"),
            storePrefetchMruInsertion = options.contains("--store-prefetch-mru-insertion"),
            storePrefetchLruVictim = options.contains("--store-prefetch-lru-victim"),
            distinctWayRelease = options.contains("--distinct-way-release"),
            ddrWriteCollectionFlow = options.contains("--ddr-write-collection-flow"),
            lineTransferDispatchFlow = options.contains("--line-transfer-dispatch-flow"),
            lineReadChannel = options.contains("--line-read-channel"),
            localPayloadWriteEnable = options.contains("--local-payload-write-enable"),
            localPayloadWriteRow = options.contains("--local-payload-write-row"),
            sharedCanonicalStoreOwnerMatch = options.contains("--shared-canonical-store-owner-match"),
            eagerFetchPrefixSelect = options.contains("--eager-fetch-prefix-select"),
            predecodedHeadDrain = options.contains("--predecoded-head-drain"),
            retirementIntent = options.contains("--retirement-intent"),
            ddrOutstanding = ddrSlots, ddrWriteCredits = ddrWrites,
            dataTlbWriteReadReuse = options.contains("--dtlb-write-read-reuse"),
            translationHitFlow = options.contains("--translation-hit-flow"),
            independentDemandAdmission = options.contains("--independent-demand-admission"),
            splitPrefetchTracking = options.contains("--split-prefetch-tracking"),
            readPrefetchDirtyRetry = options.contains("--read-prefetch-dirty-retry"),
            readPrefetchDemandAdoption = options.contains("--read-prefetch-demand-adoption"),
            readPrefetchStoreHold = options.contains("--read-prefetch-store-hold"),
            durableReadPrefetchCandidate = options.contains("--durable-read-prefetch-candidate"),
            readPrefetchBehindStore = options.contains("--read-prefetch-behind-store"),
            internalLineGrant = options.contains("--internal-line-grant"),
            concurrentReadStorePrefetch = options.contains("--concurrent-read-store-prefetch"),
            memoryScheduleOverlap = options.contains("--memory-schedule-overlap"),
            futureHomeWayReservation = options.contains("--future-home-way-reservation"),
            virtualRamLoadPrecheck = options.contains("--virtual-ram-load-precheck"),
            experimentalTriSpeedEthernet = options.contains("--experimental-trispeed-ethernet"),
            triSpeedRawClockHandoff = options.contains("--tri-speed-raw-clock-handoff"),
            independentFetchPayloadCapture = base.independentFetchPayloadCapture || options.contains("--independent-fetch-payload-capture"),
            ownerLocalIssueReady = base.ownerLocalIssueReady || options.contains("--owner-local-issue-ready"),
            sharedFetchPmpRelations = base.sharedFetchPmpRelations || options.contains("--shared-fetch-pmp-relations"),
            shareProtectedHeadPayload = base.shareProtectedHeadPayload || options.contains("--share-protected-head-payload"),
            bankedInstructionData = base.bankedInstructionData || options.contains("--banked-instruction-data"))
    }
    val sourceCommit = "ea5406ea15d2d0797ce2c5ef7a4951827c55145e"
    val hardwareSourceCommit = "3cb4298532ba28c732e7f88cef45cc9697eb7fa2"
    val naxReferenceCommit = "9f452d50560d02fb391bc8039f5453c54e0911af"
}
