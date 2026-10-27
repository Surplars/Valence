package soc.platform

import soc.core.ooo.FpgaNextConfig

/** Explicit CPU-private memory policies. A policy validates the actual final
  * configuration; it never overrides a separately supplied tile configuration.
  * This leaves the public Selected preset and common transport ABI unchanged.
  */
sealed abstract class CommonA1MemoryProfile(val name: String) {
    def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit
}

object CommonA1MemoryProfile {
    /** Four LSU owners hide checked-translation/return latency, not four L1
      * misses. The cache and common Home retain two miss owners. CPU responses
      * remain acceptance-ordered and carry no return handle across the common
      * native adapters. MMIO, atomics and unproved translations remain serial.
      * This is a functional candidate, not a frequency or board qualification.
      */
    case object ExperimentalMemoryParallel extends CommonA1MemoryProfile("experimental-memory-parallel") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false)
    }

    case object ExperimentalRegisteredTranslation extends CommonA1MemoryProfile("experimental-registered-translation") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = true)
    }

    /** Demand-hit and already-certified PA share the original checked boundary.
      * This is not the unimplemented lookahead proof-cache proposal. */
    case object ExperimentalCombinedCheckedFlow extends CommonA1MemoryProfile("experimental-combined-checked-flow") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true)
    }

    case object ExperimentalPreparedHeadStore extends CommonA1MemoryProfile("experimental-prepared-head-store") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true)
    }

    case object ExperimentalElasticLoadProof extends CommonA1MemoryProfile("experimental-elastic-load-proof") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true)
    }

    case object ExperimentalRegisteredRawCertified extends CommonA1MemoryProfile("experimental-registered-raw-certified") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = true, preparedStore = true,
                elasticProof = true, registeredRawCertified = true)
    }

    case object ExperimentalFactoredDataPmp extends CommonA1MemoryProfile("experimental-factored-data-pmp") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, factoredPmp = true)
    }

    case object ExperimentalGuardedNaturalDataPmp extends CommonA1MemoryProfile("experimental-guarded-natural-data-pmp") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true)
    }

    case object ExperimentalBufferedThirdRankProof extends CommonA1MemoryProfile("experimental-buffered-third-rank-proof") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true)
    }

    case object ExperimentalBufferedReturnFlow extends CommonA1MemoryProfile("experimental-buffered-return-flow") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true)
    }

    case object ExperimentalOrderedOwnerReady extends CommonA1MemoryProfile("experimental-ordered-owner-ready") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true,
                orderedOwnerReady = true)
    }

    case object ExperimentalAdvisoryOwner extends CommonA1MemoryProfile("experimental-advisory-owner") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true,
                orderedOwnerReady = true, advisoryExclusion = true)
    }

    /** Final DTA-port certified ingress, with no new credit, owner, or physical permission bypass. */
    case object ExperimentalCertifiedIngress extends CommonA1MemoryProfile("experimental-certified-ingress") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true,
                orderedOwnerReady = true, advisoryExclusion = true, certifiedIngress = true)
    }

    /** Strict identity-only safe-RAM frontend descendant; memory permissions and credits are unchanged. */
    case object ExperimentalIdentityFetchHorizon extends CommonA1MemoryProfile("experimental-identity-fetch-horizon") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true,
                orderedOwnerReady = true, advisoryExclusion = true, certifiedIngress = true, identityFetchHorizon = true)
    }

    /** Representation/read-port refactoring plus numerical-only operand capture.
      * Translation, physical permissions, credits and architectural retirement remain unchanged. */
    case object ExperimentalEfficiencyRefactor extends CommonA1MemoryProfile("experimental-efficiency-refactor") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true,
                orderedOwnerReady = true, advisoryExclusion = true, certifiedIngress = true,
                identityFetchHorizon = true, efficiencyRefactor = true)
    }

    case object ExperimentalEfficiencyRefactor2 extends CommonA1MemoryProfile("experimental-efficiency-refactor-2") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true,
                orderedOwnerReady = true, advisoryExclusion = true, certifiedIngress = true,
                identityFetchHorizon = true, efficiencyRefactor = true, decodedNaturalPmp = true,
                preparedBareHeadStore = true)
    }

    case object ExperimentalEfficiencyRefactor3 extends CommonA1MemoryProfile("experimental-efficiency-refactor-3") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true,
                orderedOwnerReady = true, advisoryExclusion = true, certifiedIngress = true,
                identityFetchHorizon = true, efficiencyRefactor = true, decodedNaturalPmp = true,
                preparedBareHeadStore = true, bankedRobCompletionData = true)
    }

    case object ExperimentalEfficiencyRefactor4 extends CommonA1MemoryProfile("experimental-efficiency-refactor-4") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false, combined = true, preparedStore = true,
                elasticProof = true, guardedNaturalPmp = true, bufferedThirdRank = true, bufferedReturnFlow = true,
                orderedOwnerReady = true, advisoryExclusion = true, certifiedIngress = true,
                identityFetchHorizon = true, efficiencyRefactor = true, decodedNaturalPmp = true,
                preparedBareHeadStore = true, bankedRobCompletionData = true, coexistingPhysicalLoadIngress = true)
    }

    private def validateMemory(config: FpgaNextConfig, boundary: CommonCpuTilePortParams,
        registered: Boolean, combined: Boolean = false, preparedStore: Boolean = false,
        elasticProof: Boolean = false, registeredRawCertified: Boolean = false, factoredPmp: Boolean = false,
        guardedNaturalPmp: Boolean = false, bufferedThirdRank: Boolean = false,
        bufferedReturnFlow: Boolean = false, orderedOwnerReady: Boolean = false,
        advisoryExclusion: Boolean = false, certifiedIngress: Boolean = false,
        identityFetchHorizon: Boolean = false, efficiencyRefactor: Boolean = false,
        decodedNaturalPmp: Boolean = false, preparedBareHeadStore: Boolean = false,
        bankedRobCompletionData: Boolean = false, coexistingPhysicalLoadIngress: Boolean = false): Unit = {
        val p = config.coreParams
        require(config.coexistingPhysicalLoadIngress == coexistingPhysicalLoadIngress &&
            p.coexistingPhysicalLoadIngress == coexistingPhysicalLoadIngress,
            "A1 policy must explicitly name coexisting physical load ingress")
        require(config.bankedRobCompletionData == bankedRobCompletionData &&
            p.bankedRobCompletionData == bankedRobCompletionData,
            "A1 policy must explicitly name banked ROB completion data")
        require(config.decodedNaturalPmp == decodedNaturalPmp && p.decodedNaturalPmp == decodedNaturalPmp,
            "A1 policy must explicitly name typed decoded-natural PMP")
        require(config.preparedBareHeadStoreOperands == preparedBareHeadStore &&
            p.preparedBareHeadStoreOperands == preparedBareHeadStore,
            "A1 policy must explicitly name prepared bare head-store operands")
        require(config.branchPredictorEntriesOverride == (if (efficiencyRefactor) Some(256) else None),
            "A1 policy must explicitly name the 256-entry existing bimodal candidate")
        require(!efficiencyRefactor || p.branchPredictorEntries == 256,
            "efficiency profile retains existing predictor semantics at its explicit new capacity")
        require(config.canonicalFetchCacheKeys == efficiencyRefactor && p.canonicalFetchCacheKeys == efficiencyRefactor,
            "A1 policy must explicitly name canonicalFetchCacheKeys")
        require(config.registeredMemoryOperandCapture == efficiencyRefactor && p.registeredMemoryOperandCapture == efficiencyRefactor,
            "A1 policy must explicitly name registeredMemoryOperandCapture")
        require(config.sharedMulDivOperandReads == efficiencyRefactor && p.sharedMulDivOperandReads == efficiencyRefactor,
            "A1 policy must explicitly name sharedMulDivOperandReads")
        require(config.sourceLocalLoadProofCancellation == efficiencyRefactor && p.sourceLocalLoadProofCancellation == efficiencyRefactor,
            "A1 policy must explicitly name sourceLocalLoadProofCancellation")
        require(config.sharedLoadProofPmpBounds == efficiencyRefactor && p.sharedLoadProofPmpBounds == efficiencyRefactor,
            "A1 policy must explicitly name sharedLoadProofPmpBounds")
        require(config.fetchThirdPacketLookahead == identityFetchHorizon &&
            p.fetchThirdPacketLookahead == identityFetchHorizon,
            "A1 policy must explicitly name its identity-only safe-RAM fetch horizon")
        require(!identityFetchHorizon || (certifiedIngress && config.fetchTransactionSlots == 2 &&
            p.renameWidth == 2 && p.compressedInstructions && p.registeredFetchWindow && p.alignedFetchPmp &&
            p.alignedFetchSinglePage && p.registeredTranslationHeads && p.fetchReplyTurnover &&
            p.fetchIdentityTranslation && !p.fetchAddressBeforePmp && !p.alignedFetchPermissionStage &&
            !p.fetchPreviousPacket), "identity fetch horizon retains the strict two-owner/two-result fetch pipeline")
        require(config.certifiedLoadIngress == certifiedIngress && p.certifiedLoadIngress == certifiedIngress,
            "A1 memory policy must explicitly name its certified load ingress contract")
        require(!certifiedIngress || (advisoryExclusion && orderedOwnerReady && bufferedReturnFlow &&
            guardedNaturalPmp && combined && !registered && p.virtualMemoryLevels == 3 && p.pmpEntries == 16),
            "certified ingress retains the exact guarded-natural advisory-owner VM policy")
        require(config.orderedLsuResponseReady == orderedOwnerReady &&
            p.orderedLsuResponseReady == orderedOwnerReady &&
            config.registeredAdvisoryExclusion == advisoryExclusion &&
            p.registeredAdvisoryExclusion == advisoryExclusion,
            "A1 memory policy must explicitly name ordered-owner readiness and advisory exclusion")
        require(!advisoryExclusion || orderedOwnerReady,
            "advisory exclusion is qualified only with ordered-owner readiness")
        require(!orderedOwnerReady || (bufferedReturnFlow && p.tagBits == 64 &&
            p.bufferedRamStores && p.registeredMemoryRequests && p.registeredStoreResponseOwners &&
            !p.localTaggedResponseReady),
            "ordered-owner readiness retains the fixed registered integer request and owner topology")
        require(config.bufferedReturnFlow == bufferedReturnFlow && p.bufferedReturnFlow == bufferedReturnFlow &&
            config.translatedResponseEmptyFlow == bufferedReturnFlow && p.translatedResponseEmptyFlow == bufferedReturnFlow,
            "A1 memory policy must explicitly name its two-slot buffered return flow contract")
        require(!bufferedReturnFlow || (bufferedThirdRank && guardedNaturalPmp &&
            config.reconstructIssueTokenIndex && p.reconstructIssueTokenIndex &&
            p.registeredStoreResponseOwners && !p.registeredLocalStoreResponses &&
            !p.loadCompletionBypass && !p.registeredLoadResultReady &&
            !p.fastHeadLoadRetire && !p.fastBufferedStoreRetire),
            "buffered return flow preserves stored response ownership, local ACK and registered LSU result semantics")
        require(config.bufferedThirdRankLoadProof == bufferedThirdRank &&
            p.bufferedThirdRankLoadProof == bufferedThirdRank,
            "A1 memory policy must explicitly name its buffered third-rank advisory preparation")
        require(!bufferedThirdRank || (guardedNaturalPmp && config.splitLowTagAdvance && p.splitLowTagAdvance),
            "buffered third-rank preparation requires the guarded split-tag control")
        require(config.guardedNaturalDataPmp == guardedNaturalPmp && p.guardedNaturalDataPmp == guardedNaturalPmp,
            "A1 memory policy must explicitly name its guarded natural data PMP contract")
        require(!guardedNaturalPmp || (elasticProof && combined && !registered && !registeredRawCertified && !factoredPmp),
            "guarded natural data PMP retains the old elastic topology without another PMP experiment")
        require(config.factoredDataPmpRange == factoredPmp && p.factoredDataPmpRange == factoredPmp,
            "A1 memory policy must explicitly name its generic data PMP range implementation")
        require(!factoredPmp || (elasticProof && combined && !registered && !registeredRawCertified),
            "factored data PMP retains the unregistered elastic demand-hit topology")
        require(config.registeredRawCertifiedFlow == registeredRawCertified &&
            p.registeredRawCertifiedFlow == registeredRawCertified,
            "A1 memory policy must explicitly name its registered raw/certified source separation")
        require(!registeredRawCertified || (registered && !combined),
            "registered raw/certified policy is distinct from both old M2 and combined-hit flow")
        require(config.elasticLoadProofSupply == elasticProof && p.elasticLoadProofSupply == elasticProof,
            "A1 memory policy must explicitly name its elastic load-proof preparation boundary")
        require(!elasticProof || preparedStore,
            "elastic load-proof experiment retains the explicit prepared-store checked-flow control")
        require(config.preparedHeadStoreOperands == preparedStore && p.preparedHeadStoreOperands == preparedStore,
            "A1 memory policy must explicitly name its head-store operand preparation boundary")
        require(!preparedStore || ((combined || registeredRawCertified) && p.completedCanonicalStoreForwarding &&
            p.parallelMemoryPreparation && p.parallelMemoryPayload && p.earlyStorePreparation &&
            !p.residentMemoryPayloadReuse && !p.preparedStoreLookahead),
            "prepared head-store operands retain the ordered checked-flow preparation topology")
        require(config.issueWidth == 2 && p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2,
            "A1 memory-parallel keeps the two-wide architectural backend")
        require(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.storeBufferEntries == 2,
            "A1 memory-parallel requires explicit ROB16/PRF48/LSU4/SB2 ownership")
        require(config.lsuEntries == 4 && config.dataTranslationEntries == 16 &&
            config.virtualRamLoadPrecheck && config.canonicalVirtualStoreOverlap &&
            config.independentDemandAdmission && config.translationHitFlow == !registered &&
            config.registeredDataTranslation == registered && p.registeredDataTranslation == registered &&
            config.dataTlbWriteReadReuse &&
            config.loadOrderOlderRetire,
            "A1 memory-parallel must receive its complete final memory configuration")
        require(p.virtualRamLoadPrecheck && p.canonicalVirtualStoreOverlap && p.loadOrderOlderRetire &&
            p.registeredMemoryAddress && p.registeredMemoryRequests && p.registeredTranslationHeads &&
            p.registeredTranslatedResponses && p.registeredLoadReplay && p.registeredFabricBoundary &&
            p.registeredLoadIssueForwarding,
            "A1 memory-parallel must preserve checked permission, replay and actual return boundaries")
        require(config.cache.readMshrs == 2 && config.cache.responseEntries == 2 &&
            config.cache.writebackEntries == 2 && config.cache.independentDemandAdmission &&
            config.internalLineGrant && boundary.homeAcquireEntries == 2 && boundary.homeWritebackEntries == 2,
            "A1 memory-parallel does not enlarge cache/Home transaction credits")
        require(p.dataReturnHandleBits == 0 && !p.taggedStoreReturns && p.postedProofConfig.isEmpty &&
            !p.memoryProofFrontier && !p.pendingVirtualStoreProof && !p.frozenStoreProofEnabled &&
            !p.fastBufferedStoreRetire && !p.fastHeadLoadRetire,
            "A1 memory-parallel supports ordered actual CPU replies, not tagged or posted ownership")
        require(config.precheckedDataRequestFlow == (combined || registeredRawCertified) &&
            config.combinedCheckedDataFlow == combined &&
            p.precheckedDataRequestFlow == (combined || registeredRawCertified) && p.combinedCheckedDataFlow == combined &&
            !config.physicalLoadIngressFlow && config.translatedResponseEmptyFlow == bufferedReturnFlow,
            "A1 memory policy must explicitly select certified checked flow without changing ingress or return capacity")
        require(!combined || (!registered && !config.queuedHeadSelection && config.translationHitFlow),
            "combined checked flow preserves the existing raw-hit path and head-selection topology")
    }

    /** Build from the public A1 memory baseline. All other options are retained.
      * Reject an already modified memory policy instead of silently replacing
      * its caller-selected capacities or permission/return behavior.
      * Supply the returned configuration AND the profile to CommonA1CpuTile;
      * the tile validates, but does not reapply or overwrite, this configuration.
      */
    def experimentalMemoryParallel(
        base: FpgaNextConfig = FpgaNextConfig.Selected.copy(internalLineGrant = true)
    ): FpgaNextConfig = {
        require(base.lsuEntries == 2 && base.dataTranslationEntries == 8 &&
            !base.virtualRamLoadPrecheck && !base.canonicalVirtualStoreOverlap &&
            !base.independentDemandAdmission && !base.translationHitFlow && !base.dataTlbWriteReadReuse &&
            !base.loadOrderOlderRetire && !base.registeredDataTranslation,
            "build A1 memory-parallel from the unchanged Selected memory policy, not another memory candidate")
        val result = base.copy(lsuEntries = 4, dataTranslationEntries = 16,
            virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true,
            independentDemandAdmission = true, translationHitFlow = true,
            dataTlbWriteReadReuse = true, loadOrderOlderRetire = true)
        ExperimentalMemoryParallel.validate(result, CommonCpuTilePortParams())
        result
    }
    def experimentalCombinedCheckedFlow(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalMemoryParallel.validate(base, CommonCpuTilePortParams())
        val result = base.copy(precheckedDataRequestFlow = true, combinedCheckedDataFlow = true)
        ExperimentalCombinedCheckedFlow.validate(result, CommonCpuTilePortParams())
        result
    }

    def experimentalPreparedHeadStore(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalCombinedCheckedFlow.validate(base, CommonCpuTilePortParams())
        val result = base.copy(preparedHeadStoreOperands = true)
        ExperimentalPreparedHeadStore.validate(result, CommonCpuTilePortParams())
        result
    }

    def experimentalElasticLoadProof(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalPreparedHeadStore.validate(base, CommonCpuTilePortParams())
        val result = base.copy(elasticLoadProofSupply = true)
        ExperimentalElasticLoadProof.validate(result, CommonCpuTilePortParams())
        result
    }

    /** Combinational main-PMP-only experiment: no new pipeline boundary or owner. */
    def experimentalFactoredDataPmp(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalElasticLoadProof.validate(base, CommonCpuTilePortParams())
        val result = base.copy(factoredDataPmpRange = true)
        ExperimentalFactoredDataPmp.validate(result, CommonCpuTilePortParams())
        result
    }

    /** Main-checker domain specialization with explicit rejection of malformed standalone raw inputs. */
    def experimentalGuardedNaturalDataPmp(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalElasticLoadProof.validate(base, CommonCpuTilePortParams())
        val result = base.copy(guardedNaturalDataPmp = true)
        ExperimentalGuardedNaturalDataPmp.validate(result, CommonCpuTilePortParams())
        result
    }

    /** M2 changes only the result/permission boundary, retaining all queue/cache/Home credits. */
    def experimentalRegisteredTranslation(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalMemoryParallel.validate(base, CommonCpuTilePortParams())
        val result = base.copy(translationHitFlow = false, registeredDataTranslation = true)
        ExperimentalRegisteredTranslation.validate(result, CommonCpuTilePortParams())
        result
    }

    /** Only raw demand gains the existing result-register edge. Certified PA
      * retains its checked shortcut; every capacity and old named policy stays fixed. */
    def experimentalRegisteredRawCertified(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalElasticLoadProof.validate(base, CommonCpuTilePortParams())
        val result = base.copy(registeredRawCertifiedFlow = true, registeredDataTranslation = true,
            translationHitFlow = false, combinedCheckedDataFlow = false)
        ExperimentalRegisteredRawCertified.validate(result, CommonCpuTilePortParams())
        result
    }

    /** Enable only after validating the unmodified advisory-owner control. */
    def experimentalCertifiedIngress(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalAdvisoryOwner.validate(base, CommonCpuTilePortParams())
        val result = base.copy(certifiedLoadIngress = true)
        ExperimentalCertifiedIngress.validate(result, CommonCpuTilePortParams())
        result
    }

    def experimentalEfficiencyRefactor(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalIdentityFetchHorizon.validate(base, CommonCpuTilePortParams())
        val result = base.copy(canonicalFetchCacheKeys = true, registeredMemoryOperandCapture = true,
            sharedMulDivOperandReads = true, sourceLocalLoadProofCancellation = true, sharedLoadProofPmpBounds = true,
            branchPredictorEntriesOverride = Some(256))
        ExperimentalEfficiencyRefactor.validate(result, CommonCpuTilePortParams())
        result
    }

    def experimentalEfficiencyRefactor2(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalEfficiencyRefactor.validate(base, CommonCpuTilePortParams())
        val result = base.copy(decodedNaturalPmp = true, preparedBareHeadStoreOperands = true)
        ExperimentalEfficiencyRefactor2.validate(result, CommonCpuTilePortParams())
        result
    }

    def experimentalEfficiencyRefactor3(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalEfficiencyRefactor2.validate(base, CommonCpuTilePortParams())
        val result = base.copy(bankedRobCompletionData = true)
        ExperimentalEfficiencyRefactor3.validate(result, CommonCpuTilePortParams())
        result
    }

    def experimentalEfficiencyRefactor4(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalEfficiencyRefactor3.validate(base, CommonCpuTilePortParams())
        val result = base.copy(coexistingPhysicalLoadIngress = true)
        ExperimentalEfficiencyRefactor4.validate(result, CommonCpuTilePortParams())
        result
    }

    def experimentalIdentityFetchHorizon(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalCertifiedIngress.validate(base, CommonCpuTilePortParams())
        val result = base.copy(fetchThirdPacketLookahead = true)
        ExperimentalIdentityFetchHorizon.validate(result, CommonCpuTilePortParams())
        result
    }

}
