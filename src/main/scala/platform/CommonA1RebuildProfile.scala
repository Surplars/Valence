package soc.platform

import soc.core.ooo.{FpgaNextConfig, SideEffectFreeFetchRange}

/** Explicit A/B configurations for the first A1 rebuild batch. These select
  * CPU-private structure, not a clock source, speed grade or timing sign-off.
  * Public CommonCpuProfile presets and the existing bootable SoC stay unchanged.
  */
sealed abstract class CommonA1RebuildProfile(
    val name: String,
    val dualCompletion: Boolean,
    val parallelMemory: Boolean,
    val independentBranch: Boolean = false,
    val fetchSlots: Int = 1,
    val registeredTranslation: Boolean = false,
    val circularPayload: Boolean = false,
    val completedStoreForward: Boolean = false,
    val combinedCheckedFlow: Boolean = false,
    val preparedHeadStore: Boolean = false,
    val elasticLoadProof: Boolean = false,
    // Applied after the old elastic recipe; config is the authoritative final topology.
    val registeredRawCertified: Boolean = false,
    val factoredDataPmp: Boolean = false,
    val guardedNaturalDataPmp: Boolean = false,
    val splitLowTagAdvance: Boolean = false,
    val bufferedThirdRankLoadProof: Boolean = false,
    val bufferedReturnFlow: Boolean = false,
    val orderedLsuResponseReady: Boolean = false,
    val registeredAdvisoryExclusion: Boolean = false,
    val certifiedLoadIngress: Boolean = false,
    val fetchThirdPacketLookahead: Boolean = false,
    val efficiencyRefactor: Boolean = false,
    val efficiencyRefactor2: Boolean = false,
    val efficiencyRefactor3: Boolean = false,
    val efficiencyRefactor4: Boolean = false,
    val efficiencyRefactor5: Boolean = false,
    val contextOwnedInstructionPrefetch: Boolean = false,
    val registeredMulLoadOperandCapture: Boolean = false
) {
    final def config: FpgaNextConfig = {
        val baseline = CommonCpuProfile.A1.fpga
        val memory = if (parallelMemory) CommonA1MemoryProfile.experimentalMemoryParallel(baseline) else baseline
        require(!registeredTranslation || parallelMemory, "M2 requires the explicit four-owner memory policy")
        val translation = if (registeredTranslation)
            CommonA1MemoryProfile.experimentalRegisteredTranslation(memory) else memory
        val backend = translation.copy(circularFetchPayload = circularPayload,
            completedCanonicalStoreForwarding = completedStoreForward,
            completionTopology = if (dualCompletion) "dual-owner" else "legacy",
            branchResolutionTopology = if (independentBranch) "execution-mailbox" else "writeback-coupled")
        require(!combinedCheckedFlow || (parallelMemory && !registeredTranslation),
            "combined checked flow retains the explicit demand-hit memory policy")
        val checked = if (combinedCheckedFlow)
            CommonA1MemoryProfile.experimentalCombinedCheckedFlow(backend) else backend
        require(!preparedHeadStore || (combinedCheckedFlow && completedStoreForward),
            "prepared head-store experiment builds on completed forwarding and checked flow")
        val prepared = if (preparedHeadStore) CommonA1MemoryProfile.experimentalPreparedHeadStore(checked) else checked
        require(!elasticLoadProof || preparedHeadStore,
            "elastic load-proof experiment retains the prepared-store control profile")
        val proof = if (elasticLoadProof) CommonA1MemoryProfile.experimentalElasticLoadProof(prepared) else prepared
        require(!registeredRawCertified || (elasticLoadProof && !registeredTranslation),
            "registered raw/certified experiment starts from the complete elastic checked-flow control")
        val raw = if (registeredRawCertified) CommonA1MemoryProfile.experimentalRegisteredRawCertified(proof) else proof
        require(!factoredDataPmp || (elasticLoadProof && !registeredRawCertified && !registeredTranslation),
            "factored data PMP starts from the unchanged elastic demand-hit control")
        val pmp = if (factoredDataPmp) CommonA1MemoryProfile.experimentalFactoredDataPmp(raw) else raw
        require(!guardedNaturalDataPmp || (elasticLoadProof && !registeredRawCertified &&
            !registeredTranslation && !factoredDataPmp),
            "guarded natural data PMP starts from the unchanged elastic demand-hit control")
        val guarded = if (guardedNaturalDataPmp) CommonA1MemoryProfile.experimentalGuardedNaturalDataPmp(pmp) else pmp
        require(!splitLowTagAdvance || guardedNaturalDataPmp,
            "split-low tag experiment starts from the qualified guarded-natural control")
        val tag = if (splitLowTagAdvance) guarded.copy(splitLowTagAdvance = true) else guarded
        require(!bufferedThirdRankLoadProof || (guardedNaturalDataPmp && splitLowTagAdvance),
            "buffered third-rank preparation starts from the guarded split-tag control")
        val buffered = if (bufferedThirdRankLoadProof) tag.copy(bufferedThirdRankLoadProof = true) else tag
        require(!bufferedReturnFlow || (guardedNaturalDataPmp && splitLowTagAdvance && bufferedThirdRankLoadProof),
            "buffered return flow starts only from the complete buffered third-rank control")
        // Apply the capability and both behavior flags atomically; no partially enabled descendant is legal.
        val returning = if (bufferedReturnFlow) buffered.copy(bufferedReturnFlow = true,
            translatedResponseEmptyFlow = true, reconstructIssueTokenIndex = true) else buffered
        require(!orderedLsuResponseReady || bufferedReturnFlow,
            "ordered-owner readiness extends the complete buffered-return control")
        require(!registeredAdvisoryExclusion || orderedLsuResponseReady,
            "advisory exclusion retains the ordered-owner readiness control")
        val owners = returning.copy(orderedLsuResponseReady = orderedLsuResponseReady,
            registeredAdvisoryExclusion = registeredAdvisoryExclusion)
        val frontend = if (fetchSlots == 2) owners.copy(fetchTransactionSlots = 2, alignedFetchSinglePage = true) else owners
        require(!certifiedLoadIngress || registeredAdvisoryExclusion,
            "certified ingress extends only the complete advisory-owner control")
        val ingress = if (certifiedLoadIngress) CommonA1MemoryProfile.experimentalCertifiedIngress(frontend) else frontend
        require(!fetchThirdPacketLookahead || certifiedLoadIngress,
            "identity fetch horizon extends only the complete certified-ingress control")
        val horizon = if (fetchThirdPacketLookahead) CommonA1MemoryProfile.experimentalIdentityFetchHorizon(ingress) else ingress
        require(!efficiencyRefactor || fetchThirdPacketLookahead,
            "efficiency refactor extends only the complete identity-horizon control")
        val first = if (efficiencyRefactor) CommonA1MemoryProfile.experimentalEfficiencyRefactor(horizon) else horizon
        require(!efficiencyRefactor2 || efficiencyRefactor, "second efficiency candidate retains the entire first batch")
        val second = if (efficiencyRefactor2) CommonA1MemoryProfile.experimentalEfficiencyRefactor2(first) else first
        require(!efficiencyRefactor3 || efficiencyRefactor2, "third efficiency candidate retains the entire second batch")
        val third = if (efficiencyRefactor3) CommonA1MemoryProfile.experimentalEfficiencyRefactor3(second) else second
        require(!efficiencyRefactor4 || efficiencyRefactor3, "fourth efficiency candidate retains the entire third batch")
        val fourth = if (efficiencyRefactor4) CommonA1MemoryProfile.experimentalEfficiencyRefactor4(third) else third
        require(!contextOwnedInstructionPrefetch || efficiencyRefactor4, "context prefetch retains the fourth baseline")
        require(!efficiencyRefactor5 || efficiencyRefactor4, "fifth efficiency candidate retains the entire fourth batch")
        require(!(efficiencyRefactor5 && contextOwnedInstructionPrefetch),
            "context prefetch is a fourth-baseline experiment, not a fifth nomination descendant")
        require(!registeredMulLoadOperandCapture || (efficiencyRefactor4 &&
            !efficiencyRefactor5 && !contextOwnedInstructionPrefetch),
            "MUL load capture is an isolated fourth-baseline experiment")
        if (registeredMulLoadOperandCapture) CommonA1MemoryProfile.experimentalMulLoadOperandCapture(fourth)
        else if (contextOwnedInstructionPrefetch) CommonA1MemoryProfile.experimentalContextFetchPrefetch(fourth)
        else if (efficiencyRefactor5) CommonA1MemoryProfile.experimentalEfficiencyRefactor5(fourth) else fourth
    }

    final def memoryProfile: Option[CommonA1MemoryProfile] =
        if (registeredMulLoadOperandCapture) Some(CommonA1MemoryProfile.ExperimentalMulLoadOperandCapture)
        else if (contextOwnedInstructionPrefetch) Some(CommonA1MemoryProfile.ExperimentalContextFetchPrefetch)
        else if (efficiencyRefactor5) Some(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor5)
        else if (efficiencyRefactor4) Some(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor4)
        else if (efficiencyRefactor3) Some(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor3)
        else if (efficiencyRefactor2) Some(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor2)
        else if (efficiencyRefactor) Some(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor)
        else if (fetchThirdPacketLookahead) Some(CommonA1MemoryProfile.ExperimentalIdentityFetchHorizon)
        else if (certifiedLoadIngress) Some(CommonA1MemoryProfile.ExperimentalCertifiedIngress)
        else if (registeredAdvisoryExclusion) Some(CommonA1MemoryProfile.ExperimentalAdvisoryOwner)
        else if (orderedLsuResponseReady) Some(CommonA1MemoryProfile.ExperimentalOrderedOwnerReady)
        else if (bufferedReturnFlow) Some(CommonA1MemoryProfile.ExperimentalBufferedReturnFlow)
        else if (bufferedThirdRankLoadProof) Some(CommonA1MemoryProfile.ExperimentalBufferedThirdRankProof)
        else if (guardedNaturalDataPmp) Some(CommonA1MemoryProfile.ExperimentalGuardedNaturalDataPmp)
        else if (factoredDataPmp) Some(CommonA1MemoryProfile.ExperimentalFactoredDataPmp)
        else if (registeredRawCertified) Some(CommonA1MemoryProfile.ExperimentalRegisteredRawCertified)
        else if (elasticLoadProof) Some(CommonA1MemoryProfile.ExperimentalElasticLoadProof)
        else if (preparedHeadStore) Some(CommonA1MemoryProfile.ExperimentalPreparedHeadStore)
        else if (combinedCheckedFlow) Some(CommonA1MemoryProfile.ExperimentalCombinedCheckedFlow)
        else if (registeredTranslation) Some(CommonA1MemoryProfile.ExperimentalRegisteredTranslation)
        else if (parallelMemory) Some(CommonA1MemoryProfile.ExperimentalMemoryParallel) else None

    final def buildTile(boundary: CommonCpuTilePortParams = CommonCpuTilePortParams(),
        sideEffectFreeFetchRanges: Seq[SideEffectFreeFetchRange] = Seq.empty): CommonA1CpuTile =
        new CommonA1CpuTile(config, boundary, memoryProfile, sideEffectFreeFetchRanges)
}

object CommonA1RebuildProfile {
    case object Baseline extends CommonA1RebuildProfile("baseline", false, false)
    case object Backend extends CommonA1RebuildProfile("backend", true, false)
    case object Memory extends CommonA1RebuildProfile("memory", false, true)
    case object Combined extends CommonA1RebuildProfile("combined", true, true)

    case object BackendBranch extends CommonA1RebuildProfile("backend-branch", true, false, true)
    case object CombinedBranch extends CommonA1RebuildProfile("combined-branch", true, true, true)

    case object Frontend extends CommonA1RebuildProfile("frontend", false, false, false, 2)
    case object CombinedFrontend extends CommonA1RebuildProfile("combined-frontend", true, true, false, 2)
    case object FullCandidate extends CommonA1RebuildProfile("full-candidate", true, true, true, 2)
    case object FullM2 extends CommonA1RebuildProfile("full-m2", true, true, true, 2, true)
    case object FullR1 extends CommonA1RebuildProfile("full-r1", true, true, true, 2, false, true)
    case object FullM2R1 extends CommonA1RebuildProfile("full-m2-r1", true, true, true, 2, true, true)

    case object FullR1M3 extends CommonA1RebuildProfile("full-r1-m3", true, true, true, 2, false, true, true)
    case object FullR1M3CheckedFlow extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow", true, true, true, 2, false, true, true, true)

    case object FullR1M3CheckedFlowStoreRow extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow-store-row", true, true, true, 2, false, true, true, true, true)

    case object FullR1M3CheckedFlowStoreRowElasticProof extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow-store-row-elastic-proof", true, true, true, 2, false, true, true, true, true, true)

    case object FullR1M3CheckedFlowStoreRowElasticProofRegisteredRaw extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow-store-row-elastic-proof-registered-raw",
        true, true, true, 2, false, true, true, true, true, true, true)

    case object FullR1M3CheckedFlowStoreRowElasticProofFactoredPmp extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow-store-row-elastic-proof-factored-pmp",
        true, true, true, 2, false, true, true, true, true, true, false, true)

    case object FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmp extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp",
        true, true, true, 2, false, true, true, true, true, true, false, false, true)

    case object FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmpSplitTag extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true)

    case object FullR1M3BufferedThirdRankProof extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag-buffered-third-rank",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true)

    case object FullR1M3BufferedReturnFlow extends CommonA1RebuildProfile(
        "full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag-buffered-third-rank-return-flow-index",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true)

    case object FullR1M3OrderedOwnerReady extends CommonA1RebuildProfile(
        "full-r1-m3-ordered-owner-ready",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true)

    case object FullR1M3AdvisoryOwner extends CommonA1RebuildProfile(
        "full-r1-m3-advisory-owner",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true)

    case object FullR1M3CertifiedIngress extends CommonA1RebuildProfile(
        "full-r1-m3-certified-ingress",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true)

    case object FullR1M3IdentityFetchHorizon extends CommonA1RebuildProfile(
        "full-r1-m3-identity-fetch-horizon",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true,
        fetchThirdPacketLookahead = true)

    case object FullR1M3EfficiencyRefactor extends CommonA1RebuildProfile(
        "full-r1-m3-efficiency-refactor",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true,
        fetchThirdPacketLookahead = true, efficiencyRefactor = true)

    case object FullR1M3EfficiencyRefactor2 extends CommonA1RebuildProfile(
        "full-r1-m3-efficiency-refactor-2",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true,
        fetchThirdPacketLookahead = true, efficiencyRefactor = true, efficiencyRefactor2 = true)

    case object FullR1M3EfficiencyRefactor3 extends CommonA1RebuildProfile(
        "full-r1-m3-efficiency-refactor-3",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true,
        fetchThirdPacketLookahead = true, efficiencyRefactor = true, efficiencyRefactor2 = true,
        efficiencyRefactor3 = true)

    case object FullR1M3EfficiencyRefactor4 extends CommonA1RebuildProfile(
        "full-r1-m3-efficiency-refactor-4",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true,
        fetchThirdPacketLookahead = true, efficiencyRefactor = true, efficiencyRefactor2 = true,
        efficiencyRefactor3 = true, efficiencyRefactor4 = true)

    case object FullR1M3ContextFetchPrefetchExperiment extends CommonA1RebuildProfile(
        "full-r1-m3-context-fetch-prefetch-experiment",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true,
        fetchThirdPacketLookahead = true, efficiencyRefactor = true, efficiencyRefactor2 = true,
        efficiencyRefactor3 = true, efficiencyRefactor4 = true, contextOwnedInstructionPrefetch = true)

    case object FullR1M3MulLoadOperandCaptureExperiment extends CommonA1RebuildProfile(
        "full-r1-m3-mul-load-operand-capture-experiment",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true,
        fetchThirdPacketLookahead = true, efficiencyRefactor = true, efficiencyRefactor2 = true,
        efficiencyRefactor3 = true, efficiencyRefactor4 = true, registeredMulLoadOperandCapture = true)

    case object FullR1M3EfficiencyRefactor5 extends CommonA1RebuildProfile(
        "full-r1-m3-efficiency-refactor-5",
        true, true, true, 2, false, true, true, true, true, true, false, false, true, true, true, true,
        orderedLsuResponseReady = true, registeredAdvisoryExclusion = true, certifiedLoadIngress = true,
        fetchThirdPacketLookahead = true, efficiencyRefactor = true, efficiencyRefactor2 = true,
        efficiencyRefactor3 = true, efficiencyRefactor4 = true, efficiencyRefactor5 = true)

    lazy val all: Seq[CommonA1RebuildProfile] = Seq(Baseline, Backend, Memory, Combined, BackendBranch, CombinedBranch,
        Frontend, CombinedFrontend, FullCandidate, FullM2, FullR1, FullM2R1, FullR1M3, FullR1M3CheckedFlow,
        FullR1M3CheckedFlowStoreRow, FullR1M3CheckedFlowStoreRowElasticProof,
        FullR1M3CheckedFlowStoreRowElasticProofRegisteredRaw, FullR1M3CheckedFlowStoreRowElasticProofFactoredPmp,
        FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmp,
        FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmpSplitTag, FullR1M3BufferedThirdRankProof,
        FullR1M3BufferedReturnFlow, FullR1M3OrderedOwnerReady, FullR1M3AdvisoryOwner, FullR1M3CertifiedIngress,
        FullR1M3IdentityFetchHorizon, FullR1M3EfficiencyRefactor, FullR1M3EfficiencyRefactor2,
        FullR1M3EfficiencyRefactor3, FullR1M3EfficiencyRefactor4, FullR1M3EfficiencyRefactor5, FullR1M3ContextFetchPrefetchExperiment,
        FullR1M3MulLoadOperandCaptureExperiment)

    def named(name: String): CommonA1RebuildProfile = {
        require(all.exists(_.name == name), s"unknown explicit A1 rebuild profile: $name")
        all.find(_.name == name).get
    }
}
