package soc.core.ooo

import chisel3.util.log2Ceil

/** Initial integer backend parameters. Wider product profiles are not implemented presets. */
case class OooParams(
    renameWidth: Int = 2,
    commitWidth: Int = 2,
    completionWidth: Int = 2,
    robEntries: Int = 32,
    physicalRegs: Int = 64,
    tagBits: Int = 64,
    speculativeRamBase: BigInt = 0,
    speculativeRamBytes: BigInt = 0,
    memoryEntries: Int = 4,
    branchPredictorEntries: Int = 64,
    bufferedRamStores: Boolean = false,
    registeredLocalStoreResponses: Boolean = false,
    registeredImsicInterrupts: Boolean = false,
    registeredMemoryRequests: Boolean = false,
    registeredStoreResponseOwners: Boolean = false,
    registeredBranchRedirect: Boolean = false,
    registeredMemoryAddress: Boolean = false,
    registeredRobRetirement: Boolean = false,
    registeredLoadReplay: Boolean = false,
    parallelRenameAdmission: Boolean = false,
    stableFetchFaultMetadata: Boolean = false,
    precompleteMispredictedBranch: Boolean = false,
    earlyRankedOperands: Boolean = false,
    pcDerivedReturnLinks: Boolean = false,
    earlyRenameDestinations: Boolean = false,
    parallelPrfReadyUpdates: Boolean = false,
    stablePredictionMetadata: Boolean = false,
    balancedBranchCompare: Boolean = false,
    separateBranchRetireFault: Boolean = false,
    parallelReturnStackControl: Boolean = false,
    earlyRedirectCapture: Boolean = false,
    parallelMemoryPreparation: Boolean = false,
    alignedFetchPmp: Boolean = false,
    parallelIssuePayload: Boolean = false,
    rawFetchPresence: Boolean = false,
    oneHotPhysicalOperands: Boolean = false,
    registeredTranslatedResponses: Boolean = false,
    directMemoryResponse: Boolean = false,
    parallelFetchAddresses: Boolean = false,
    prefixTileLinkDecode: Boolean = false,
    rawTileLinkResponseMetadata: Boolean = false,
    bufferedRomReplies: Boolean = false,
    parallelPredictionQualification: Boolean = false,
    parallelRecoveryAdmission: Boolean = false,
    parallelRedirectTokens: Boolean = false,
    parallelIssueRanks: Boolean = false,
    parallelAluResults: Boolean = false,
    parallelCompletionPayload: Boolean = false,
    parallelFetchTagLookup: Boolean = false,
    parallelFrontendControl: Boolean = false,
    parallelAuipcQualification: Boolean = false,
    parallelPredictionSources: Boolean = false,
    parallelAddressSums: Boolean = false,
    bufferedFetchRequests: Boolean = false,
    parallelFetchAlignment: Boolean = false,
    parallelDecodeLegality: Boolean = false,
    flowThroughFetchRequests: Boolean = false,
    parallelMinMaxResults: Boolean = false,
    parallelBitLegality: Boolean = false,
    parallelRenameRanks: Boolean = false,
    parallelMinMaxWordResults: Boolean = false,
    parallelArchitecturalDestinations: Boolean = false,
    parallelAluWordResults: Boolean = false,
    independentFetchCapture: Boolean = false,
    parallelHomeQualification: Boolean = false,
    registeredFabricBoundary: Boolean = false,
    registeredTranslationHeads: Boolean = false,
    fetchReplyTurnover: Boolean = false,
    fetchIdentityTranslation: Boolean = false,
    registeredPredictionTraining: Boolean = false,
    parallelMemoryPayload: Boolean = false,
    parallelPacketPmp: Boolean = false,
    registeredIssueExecute: Boolean = false,
    registeredFetchPacket: Boolean = false,
    wordSpanPacketPmp: Boolean = false,
    parallelFetchValidation: Boolean = false,
    fetchHintEntries: Int = 8,
    balancedPacketPmp: Boolean = false,
    compactMemoryOperandSelect: Boolean = false,
    parallelMemoryAddressSum: Boolean = false,
    capturedFetchPermission: Boolean = false,
    splitFetchCursor: Boolean = false,
    registeredFetchWindow: Boolean = false,
    fastHeadTrapRecovery: Boolean = false,
    fastHeadSystemRecovery: Boolean = false,
    tentativeRenameSources: Boolean = false,
    sharedPhysicalSourceDecode: Boolean = false,
    ownerLocalOperandReady: Boolean = false,
    earlyStorePreparation: Boolean = false,
    parallelMulDivDispatch: Boolean = false,
    registeredMulDivOperands: Boolean = false,
    registeredIssueHeadMask: Boolean = false,
    unconditionalMemoryPayloadCapture: Boolean = false,
    earlyRecoveryIssueBlock: Boolean = false,
    fastBufferedStoreRetire: Boolean = false,
    fastHeadLoadRetire: Boolean = false,
    loadCompletionBypass: Boolean = false,
    registeredLoadIssueForwarding: Boolean = false,
    mulWordPreviewBypass: Boolean = false,
    moveAlias: Boolean = false,
    flowTileLinkResponse: Boolean = false,
    storeBufferEntries: Int = 4,
    machineSystem: Boolean = false,
    experimentalFloatingPoint: Boolean = false,
    floatingPoint: FloatingPointConfig = FloatingPointConfig.disabled,
    advertiseFloatingPoint: Boolean = false,
    atomicMemory: Boolean = false,
    pmpEntries: Int = 0,
    virtualMemoryLevels: Int = 0,
    compressedInstructions: Boolean = false,
    instructionCacheSets: Int = 0,
    returnStackEntries: Int = 16,
    indirectTargetEntries: Int = 0,
    recoveryWidth: Int = 1,
    identityDataRequestFlow: Boolean = false,
    bankedRobPayload: Boolean = false,
    sharedStoreOperandReads: Boolean = false,
    lvtPhysicalRegisterFile: Boolean = false,
    dataNextLinePrefetch: Boolean = false,
    virtualRamLoadPrecheck: Boolean = false,
    bankedIssuePayload: Boolean = false,
    bankedFetchHints: Boolean = false,
    independentFetchPayloadCapture: Boolean = false,
    ownerLocalIssueReady: Boolean = false,
    sharedFetchPmpRelations: Boolean = false,
    shareProtectedHeadPayload: Boolean = false
) {
    require(!shareProtectedHeadPayload || (bankedIssuePayload && machineSystem && compressedInstructions && fpEnabled && fastHeadSystemRecovery),
        "protected head payload sharing requires banked storage, compressed FP and the protected head-token observation")
    require(!sharedFetchPmpRelations || (wordSpanPacketPmp && parallelPacketPmp && pmpEntries > 0),
        "shared fetch PMP relations require the word-span packet permission profile")
    require(!ownerLocalIssueReady || (ownerLocalOperandReady && registeredIssueExecute &&
        !loadCompletionBypass && !mulWordPreviewBypass),
        "owner-local ALU issue readiness needs exact ready mirrors and registered execution promises")
    require(!bankedIssuePayload || (renameWidth == 2 && robEntries >= 4),
        "banked issue payload requires contiguous two-wide allocation")
    require(!bankedFetchHints || registeredFetchPacket,
        "banked fetch hints require the registered fetch reservoir")
    require(!virtualRamLoadPrecheck || (machineSystem && pmpEntries > 0 && virtualMemoryLevels > 0 &&
        registeredMemoryAddress && memoryEntries >= 2 && speculativeRamBytes > 0),
        "virtual RAM load precheck requires staged addresses, VM/PMP and parallel explicit RAM ownership")
    require(!dataNextLinePrefetch || (machineSystem && pmpEntries > 0 && virtualMemoryLevels > 0),
        "data prefetch requires the machine privilege/PMP/translation guard")
    require(!lvtPhysicalRegisterFile || (completionWidth == 2 && !fastHeadLoadRetire),
        "owner-banked PRF requires two completion writers and no fast-head-load third writer")
    require(!sharedStoreOperandReads || (earlyStorePreparation && parallelIssuePayload && registeredIssueExecute),
        "shared store operands require existing two-lane registered store preparation")
    require(!bankedRobPayload || (renameWidth == 2 && commitWidth == 2 && robEntries >= 4),
        "banked ROB payload requires two-wide contiguous allocation and retirement")
    require(
        Seq(renameWidth, commitWidth, completionWidth).forall(w => w >= 1 && w <= 6),
        "each backend port width must be between one and six"
    )
    require(
        robEntries >= Seq(2, renameWidth, commitWidth).max && isPow2(robEntries),
        "ROB capacity must be a power of two, at least two, and cover allocation/commit widths"
    )
    require(physicalRegs > 32 && physicalRegs <= 256, "integer PRF needs more than 32 and at most 256 entries")
    // Legacy experimentalFloatingPoint enables the complete candidate; new users
    // select F or F+D explicitly. Experimental subsets never advertise full F/D.
    def fpConfig: FloatingPointConfig = if (experimentalFloatingPoint && !floatingPoint.f)
        FloatingPointConfig.fullFD else floatingPoint
    def fpEnabled: Boolean = fpConfig.f
    require(!fpEnabled || machineSystem, "FP requires machine-system mode")
    require(!advertiseFloatingPoint || (fpEnabled && fpConfig.complete),
        "ISA advertisement requires every instruction group of the selected F/D extension")
    def misaValue: BigInt = (BigInt(2) << 62) | (BigInt(1) << 8) | (BigInt(1) << 12) |
        (BigInt(1) << 18) | (BigInt(1) << 20) |
        (if (atomicMemory) BigInt(1) else BigInt(0)) |
        (if (compressedInstructions) BigInt(1) << 2 else BigInt(0)) |
        (if (advertiseFloatingPoint) BigInt(1) << 5 else BigInt(0)) |
        (if (advertiseFloatingPoint && fpConfig.d) BigInt(1) << 3 else BigInt(0))
    def advertisedIsa: String = "rv64im" + (if (atomicMemory) "a" else "") +
        (if (advertiseFloatingPoint) "f" else "") +
        (if (advertiseFloatingPoint && fpConfig.d) "d" else "") +
        (if (compressedInstructions) "c" else "") +
        (if (machineSystem) "_zicsr_zifencei" else "")
    require(tagBits >= 8 && tagBits <= 64, "allocation tag width must be between 8 and 64")
    require(Set(8, 16, 32).contains(fetchHintEntries), "fetch successor hints support 8/16/32 entries")
    require(!wordSpanPacketPmp || parallelPacketPmp, "word-span PMP requires packet PMP")
    require(!parallelFetchValidation || registeredFetchPacket, "parallel validation requires fetch reservoir")
    require(!capturedFetchPermission || (registeredFetchPacket && parallelPacketPmp),
        "captured fetch permissions require the packet reservoir and parallel PMP")
    require(!splitFetchCursor || registeredFetchPacket, "split cursor requires fetch reservoir")
    require(!registeredFetchWindow || (compressedInstructions && registeredFetchPacket),
        "registered cache window requires compressed packets and the fetch reservoir")

    require(
        speculativeRamBase >= 0 && speculativeRamBytes >= 0 &&
            speculativeRamBase + speculativeRamBytes <= (BigInt(1) << 64),
        "invalid speculative RAM range"
    )

    require(
        !atomicMemory || (speculativeRamBytes >= 64 && speculativeRamBase % 64 == 0 && speculativeRamBytes % 64 == 0),
        "atomics require an explicit RAM window with whole reservation granules"
    )
    require(Set(1, 2, 4, 8).contains(memoryEntries), "memory slots must be 1, 2, 4 or 8")
    require(Set(0, 16, 32, 64).contains(indirectTargetEntries), "indirect target entries must be 0, 16, 32 or 64")
    require(Set(1, 2, 4, 8).contains(storeBufferEntries), "store buffer must have 1, 2, 4 or 8 entries")
    require(Set(0, 8, 16).contains(pmpEntries) && (pmpEntries == 0 || machineSystem),
        "PMP requires machine-system mode and supports 0, 8 or 16 entries")
    require(Set(0, 3, 4, 5).contains(virtualMemoryLevels) &&
        (virtualMemoryLevels == 0 || (machineSystem && pmpEntries > 0)),
        "virtual memory control requires machine-system mode, PMP and Sv39/Sv48/Sv57")
    require(!bufferedRamStores || speculativeRamBytes > 0, "buffered writes require an explicit no-write-error RAM")
    require(!registeredLocalStoreResponses || bufferedRamStores,
        "registered StoreBuffer local responses require RAM buffering")
    require(!registeredMemoryRequests || bufferedRamStores,
        "registered LSU requests require the ordered StoreBuffer data port")
    require(!registeredStoreResponseOwners || bufferedRamStores,
        "registered StoreBuffer response owners require RAM buffering")
    require(!registeredMemoryAddress || !fastBufferedStoreRetire,
        "registered memory addresses cannot use same-cycle buffered store retirement")
    require(!earlyRecoveryIssueBlock || registeredBranchRedirect,
        "early recovery issue blocking requires registered branch redirects")
    require(!earlyRankedOperands || (registeredBranchRedirect && completionWidth == 2 && !fastBufferedStoreRetire),
        "early ranked operands require the two-slot ranked scheduler without direct store retirement")
    require(!earlyRenameDestinations || (parallelRenameAdmission && !moveAlias),
        "early destination candidates require parallel admission and non-aliased fresh-register allocation")
    require(!separateBranchRetireFault || (registeredBranchRedirect && registeredRobRetirement),
        "separate branch retirement faults require registered branch redirect and retirement")
    require(!earlyRedirectCapture || registeredBranchRedirect,
        "early redirect capture requires registered branch redirects")
    require(!parallelRedirectTokens || registeredBranchRedirect,
        "parallel redirect token qualification requires registered branch redirects")
    require(!parallelIssueRanks || parallelIssuePayload,
        "parallel issue ranks require the two-slot circular payload scheduler")
    require(!registeredIssueHeadMask || parallelIssueRanks,
        "registered age boundary requires the circular ranked issue profile")
    require(!unconditionalMemoryPayloadCapture || (registeredMemoryAddress && parallelMemoryPayload),
        "always-captured memory payload requires early parallel candidates and a separate valid register")
    require(!parallelFetchTagLookup || compressedInstructions,
        "parallel fetch tag lookup requires the packet-aligned compressed frontend")
    require(!parallelAuipcQualification || (parallelFrontendControl && parallelPredictionQualification),
        "parallel AUIPC qualification requires dedicated frontend control and PC-relative qualification")
    require(!parallelPredictionSources || (parallelFrontendControl && parallelPredictionQualification),
        "parallel source qualification requires dedicated frontend control and PC-relative qualification")
    require(!parallelFetchAlignment || compressedInstructions, "parallel alignment requires compressed fetch")
    require(!flowThroughFetchRequests || bufferedFetchRequests, "request flow requires occupancy-only buffering")
    require(!independentFetchCapture || flowThroughFetchRequests,
        "independent capture requires the flow-through request boundary")
    require(!registeredFabricBoundary || (parallelHomeQualification && independentFetchCapture),
        "registered fabric boundary builds on the request-capture profile")
    require(!registeredTranslationHeads || (registeredFabricBoundary && registeredTranslatedResponses),
        "translation heads require the registered request and response boundaries")
    require(!identityDataRequestFlow || registeredTranslationHeads,
        "identity data flow requires registered translation ingress")
    require(!(fetchReplyTurnover || fetchIdentityTranslation) || registeredTranslationHeads,
        "fetch turnover and identity capture require registered translation heads")
    require(!parallelMemoryPayload || (parallelMemoryPreparation && completionWidth == 2),
        "parallel memory payload requires the two-candidate memory planner")
    require(!parallelPacketPmp || compressedInstructions,
        "parallel packet PMP requires the halfword packet frontend")
    require(!registeredIssueExecute || (completionWidth == 2 && registeredBranchRedirect &&
        precompleteMispredictedBranch && registeredRobRetirement && !fastBufferedStoreRetire &&
        !fastHeadLoadRetire && !moveAlias),
        "operand execution stages require the two-slot non-aliased registered redirect/retirement contract")
    require(!registeredLoadIssueForwarding || (registeredIssueExecute && !loadCompletionBypass),
        "load issue forwarding requires registered operand capture and excludes broad load bypass")
    require(!registeredFetchPacket || renameWidth <= 4,
        "registered fetch reservoir supports one to four admission lanes")
    require(!fastHeadTrapRecovery || parallelRecoveryAdmission,
        "trusted current-head trap recovery requires parallel ordinary recovery admission")
    require(!fastHeadSystemRecovery || parallelRecoveryAdmission,
        "trusted current-head system recovery requires parallel ordinary recovery admission")
    require(!tentativeRenameSources || renameWidth == 2,
        "fault-aware scalar rename candidates currently require the two-lane baseline")
    require(!sharedPhysicalSourceDecode || (completionWidth == 2 &&
        !loadCompletionBypass && !mulWordPreviewBypass &&
        (parallelMemoryPayload || earlyStorePreparation || parallelMulDivDispatch || oneHotPhysicalOperands)),
        "shared queued-source decode requires independent two-owner physical reads without late preview bypass")
    require(!ownerLocalOperandReady || (parallelPrfReadyUpdates && !loadCompletionBypass && !mulWordPreviewBypass),
        "owner-local readiness requires precise parallel wake/reserve updates without late preview bypass")
    require(!earlyStorePreparation || (parallelIssuePayload && registeredIssueExecute && completionWidth == 2 &&
        !loadCompletionBypass && !mulWordPreviewBypass),
        "early store payloads require the two-slot staged issue scheduler without late preview bypass")
    require(!parallelMulDivDispatch || (parallelIssuePayload && completionWidth == 2 &&
        !loadCompletionBypass && !mulWordPreviewBypass),
        "parallel M-unit payloads require two issue slots without late preview bypass")
    require(!parallelArchitecturalDestinations || earlyRenameDestinations,
        "early architectural destinations need early rename")
    require(!parallelAluWordResults || (parallelMinMaxWordResults && parallelAddressSums),
        "early W/address results need parallel minmax W and fixed-shift sums")
    require(!parallelBitLegality || parallelDecodeLegality, "parallel B legality needs parallel class legality")
    require(!parallelRenameRanks || earlyRenameDestinations, "parallel ranks need early destinations")
    require(!parallelMinMaxWordResults || (parallelAluResults && parallelMinMaxResults),
        "early min/max W data needs parallel result selection")
    require(!parallelMinMaxResults || parallelAluResults, "parallel min/max requires parallel results")
    require(!parallelAddressSums || parallelAluResults,
        "parallel Zba address sums require parallel ALU result selection")
    require(!parallelMemoryPreparation ||
        (registeredMemoryAddress && !fastBufferedStoreRetire && !loadCompletionBypass && !mulWordPreviewBypass),
        "parallel memory preparation needs staged addresses and no late operand/direct-store bypass")
    require(!alignedFetchPmp || compressedInstructions,
        "aligned fetch PMP requires the packet-aligned compressed frontend")
    require(!parallelIssuePayload || (earlyRankedOperands && precompleteMispredictedBranch),
        "parallel issue payload needs the two-slot early ranked scheduler and precompleted branches")
    require(!rawFetchPresence || (compressedInstructions && stableFetchFaultMetadata),
        "raw fetch presence requires compressed packets and validity-independent fault metadata")
    require(!oneHotPhysicalOperands || (parallelIssuePayload && !loadCompletionBypass && !mulWordPreviewBypass),
        "one-hot physical operands require ranked payload owners without late preview bypass")
    require(!parallelReturnStackControl || (compressedInstructions && commitWidth == 2),
        "parallel return-stack control requires the two-lane compressed-instruction frontend")
    require(!registeredLoadReplay ||
        (registeredMemoryAddress && registeredRobRetirement && earlyRecoveryIssueBlock &&
            !fastHeadLoadRetire && !fastBufferedStoreRetire),
        "registered load replay needs staged memory, registered retirement, early recovery blocking and no fast retire")
    require(!precompleteMispredictedBranch ||
        (registeredBranchRedirect && registeredRobRetirement && !fastHeadLoadRetire && !fastBufferedStoreRetire),
        "early mispredicted-branch completion needs registered redirect/retirement without fast head retirement")
    require(!fastBufferedStoreRetire || bufferedRamStores,
        "same-cycle buffered store retirement requires guaranteed-success RAM buffering")

    require(
        branchPredictorEntries >= 2 && branchPredictorEntries <= 256 && isPow2(branchPredictorEntries),
        "branch predictor entries must be a power of two between 2 and 256"
    )
    val frontendCacheSets: Int = if (instructionCacheSets == 0) {
        if (renameWidth >= 4) 128 else 64
    } else instructionCacheSets
    require(frontendCacheSets >= 2 && frontendCacheSets <= 256 && isPow2(frontendCacheSets),
        "instruction cache sets must be automatic or a power of two between 2 and 256")
    require(returnStackEntries >= 2 && returnStackEntries <= 32 && isPow2(returnStackEntries),
        "return stack entries must be a power of two between 2 and 32")
    require(Set(1, 2, 4, 8, 16).contains(recoveryWidth) && recoveryWidth <= robEntries,
        "recovery width must be 1, 2, 4, 8 or 16 and fit the ROB")

    // A memory start shares the ALU issue budget. Completion ports are separately arbitrated.
    val issueWidth: Int = completionWidth
    val robBits: Int    = log2Ceil(robEntries)
    val physBits: Int   = log2Ceil(physicalRegs)
    val countBits: Int  = log2Ceil(robEntries + 1)

    private def isPow2(value: Int): Boolean = value > 0 && (value & (value - 1)) == 0
}
