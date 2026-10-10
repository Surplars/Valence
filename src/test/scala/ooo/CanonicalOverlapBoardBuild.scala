package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.FpgaNextConfig

/** Shared by the CLI emitter and the actual ON/OFF elaboration test. */
object CanonicalOverlapBoardBuild {
    def build(c: FpgaNextConfig, overlap: Boolean, lineageProbes: Boolean = false): CanonicalOverlapBoardGsim = new CanonicalOverlapBoardGsim(
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
        postedPrefetchHeadOffer = c.postedPrefetchHeadOffer, canonicalVirtualStoreOverlap = overlap, backendCapacity = c.backendCapacity,
        lineageProfile = if (lineageProbes) Some(c) else None)
}

