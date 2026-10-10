package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.FpgaNextConfig

/** Shared by the CLI emitter and the actual ON/OFF elaboration test. */
object FpgaNextBoardGsim {
    def build(c: FpgaNextConfig, lineageProbes: Boolean = false): BoardSocGsim = new BoardSocGsim(
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
        bankedInstructionData = c.bankedInstructionData, dmaLineTransfers = c.dmaLineTransfers,
        dmaLineYieldCycles = c.dmaLineYieldCycles, dmaLineEntries = c.dmaLineEntries,
        precheckedDataRequestFlow = c.precheckedDataRequestFlow, physicalLoadIngressFlow = c.physicalLoadIngressFlow,
        loadOrderOlderRetire = c.loadOrderOlderRetire, fetchPreviousPacket = c.fetchPreviousPacket,
        preparedStoreLookahead = c.preparedStoreLookahead,
        translatedResponseEmptyFlow = c.translatedResponseEmptyFlow,
        dataTranslationEntries = c.dataTranslationEntries, postedStoreMerge = c.postedStoreMerge,
        postedPrefetchHeadOffer = c.postedPrefetchHeadOffer,
        canonicalVirtualStoreOverlap = c.canonicalVirtualStoreOverlap,
        lineageProfile = if (lineageProbes) Some(c) else None)
}

/** Same fixed CPU/cache/fabric profile as the native export, without clock-domain peripherals. */
object FpgaNextBoardGsimMain extends App {
    val options = args.drop(1).toSet
    require(args.nonEmpty && options.size == args.length - 1 &&
        options.subsetOf(Set("--canonical-virtual-store-overlap", "--posted-prefetch-coexistence", "--posted-store-merge", "--posted-prefetch-head-offer", "--translated-response-empty-flow", "--store-prefetch-mru-insertion", "--store-next-line-prefetch", "--prepared-store-lookahead", "--data-translation-entries=4", "--data-translation-entries=8",
            "--data-translation-entries=16", "--data-translation-entries=32", "--fetch-previous-packet", "--load-order-older-retire", "--lsu-entries=2", "--lsu-entries=4", "--dma-line-entries=1", "--dma-line-entries=2", "--dma-line-entries=4", "--dma-line-yield-cycles=0", "--dma-line-yield-cycles=4", "--dma-line-yield-cycles=8", "--dma-line-yield-cycles=16", "--dma-line-yield-cycles=32", "--dma-line-yield-cycles=64", "--dma-line-transfers", "--prefetch-break-on-store", "--prefetch-candidate-cycles=1", "--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16", "--selected", "--share-protected-head-payload", "--banked-instruction-data", "--owner-local-issue-ready", "--shared-fetch-pmp-relations", "--independent-fetch-payload-capture", "--reference", "--candidate", "--virtual-ram-load-precheck", "--physical-load-ingress-flow", "--prechecked-data-flow")) &&
        !(options.contains("--reference") && options.contains("--candidate")),
        "usage: FpgaNextBoardGsimMain output-directory [--reference|--candidate] [--virtual-ram-load-precheck] [--fetch-previous-packet] [--data-translation-entries=4|8|16|32] [--prepared-store-lookahead] [--store-next-line-prefetch] [--store-prefetch-mru-insertion] [--posted-store-merge] [--posted-prefetch-coexistence] [--posted-prefetch-head-offer] [--canonical-virtual-store-overlap] [--translated-response-empty-flow]")
    val c = FpgaNextConfig.fromOptions(options, defaultSelected = false)
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c),
        Array("--target-dir", args(0)))
}
