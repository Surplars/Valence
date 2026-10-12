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
        canonicalVirtualStoreOverlap = c.canonicalVirtualStoreOverlap, memoryProofFrontier = c.memoryProofFrontier,
        frozenStoreProofTransport = c.frozenStoreProofTransport, pendingVirtualStoreProof = c.pendingVirtualStoreProof,
        registeredPendingStoreQuery = c.registeredPendingStoreQuery,
        alignedFetchPermissionStage = c.alignedFetchPermissionStage,
        sharedLane1OwnerMatch = c.sharedLane1OwnerMatch,
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
    val options = args.drop(1).toSet
    require(args.nonEmpty && options.size == args.length - 1 &&
        options.subsetOf(Set("--rob-entries=16", "--rob-entries=32", "--rob-entries=64",
            "--registered-pmp-regions", "--published-pmp-changes", "--ddr-write-collection-flow",
            "--line-transfer-dispatch-flow",
            "--line-read-channel", "--split-prefetch-tracking", "--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption", "--read-prefetch-store-hold",
            "--durable-read-prefetch-candidate", "--read-prefetch-behind-store",
            "--dtlb-write-read-reuse", "--translation-hit-flow", "--independent-demand-admission", "--dma-line-entries=8",
            "--ddr-outstanding=4", "--ddr-outstanding=8",
            "--ddr-write-credits=1", "--ddr-write-credits=2", "--ddr-write-credits=4",
            "--physical-regs=48", "--physical-regs=64", "--canonical-virtual-store-overlap", "--memory-proof-frontier", "--frozen-store-proof-transport", "--pending-virtual-store-proof", "--registered-pending-store-query", "--aligned-fetch-permission-stage", "--registered-canonical-store-event", "--shared-lane1-owner-match", "--bound-head-store-overlap", "--pending-ready-store-bypass", "--tagged-store-returns", "--pending-virtual-store-proof-slots=1", "--pending-virtual-store-proof-slots=2", "--pending-store-early-load-credits=1", "--pending-store-early-load-credits=2", "--posted-prefetch-coexistence", "--posted-store-merge", "--posted-prefetch-head-offer", "--translated-response-empty-flow", "--store-prefetch-mru-insertion", "--store-prefetch-lru-victim", "--distinct-way-release", "--store-next-line-prefetch", "--prepared-store-lookahead", "--posted-preparation-priority", "--reconstruct-issue-token-index", "--shared-memory-address-state", "--data-translation-entries=4", "--data-translation-entries=8",
            "--data-translation-entries=16", "--data-translation-entries=32", "--fetch-previous-packet", "--load-order-older-retire", "--lsu-entries=2", "--lsu-entries=4", "--dma-line-entries=1", "--dma-line-entries=2", "--dma-line-entries=4", "--dma-line-yield-cycles=0", "--dma-line-yield-cycles=4", "--dma-line-yield-cycles=8", "--dma-line-yield-cycles=16", "--dma-line-yield-cycles=32", "--dma-line-yield-cycles=64", "--dma-line-transfers", "--prefetch-break-on-store", "--prefetch-candidate-cycles=1", "--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16", "--selected", "--share-protected-head-payload", "--banked-instruction-data", "--owner-local-issue-ready", "--shared-fetch-pmp-relations", "--independent-fetch-payload-capture", "--reference", "--candidate", "--virtual-ram-load-precheck", "--physical-load-ingress-flow", "--prechecked-data-flow")) &&
        !(options.contains("--reference") && options.contains("--candidate")),
        "usage: FpgaNextBoardGsimMain output-directory [--reference|--candidate] [--rob-entries=16|32|64] [--physical-regs=48|64] [--virtual-ram-load-precheck] [--fetch-previous-packet] [--data-translation-entries=4|8|16|32] [--prepared-store-lookahead] [--posted-preparation-priority] [--reconstruct-issue-token-index] [--shared-memory-address-state] [--store-next-line-prefetch] [--split-prefetch-tracking] [--read-prefetch-dirty-retry] [--read-prefetch-demand-adoption] [--read-prefetch-store-hold] [--durable-read-prefetch-candidate] [--read-prefetch-behind-store] [--registered-pmp-regions] [--published-pmp-changes] [--store-prefetch-mru-insertion] [--store-prefetch-lru-victim] [--distinct-way-release] [--posted-store-merge] [--posted-prefetch-coexistence] [--posted-prefetch-head-offer] [--canonical-virtual-store-overlap] [--memory-proof-frontier] [--translated-response-empty-flow]")
    val c = FpgaNextConfig.fromOptions(options, defaultSelected = false)
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true),
        Array("--target-dir", args(0)))
}
