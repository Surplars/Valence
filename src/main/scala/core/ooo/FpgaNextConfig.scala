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
    robEntries: Option[Int] = None,
    physicalRegs: Option[Int] = None,
    storePrefetchLruVictim: Boolean = false
) {
    val backendCapacity = BackendCapacityConfig(robEntries, physicalRegs)
    SvTranslationService.indexBits(dataTranslationEntries)
    require(!memoryProofFrontier || (robEntries.contains(64) && physicalRegs.contains(64) && lsuEntries == 4 &&
        virtualRamLoadPrecheck && canonicalVirtualStoreOverlap && loadOrderOlderRetire && dataTranslationEntries == 16),
        "memory proof frontier requires the explicitly selected reviewed capacity and translation profile")
    require(!canonicalVirtualStoreOverlap || virtualRamLoadPrecheck,
        "canonical virtual store overlap requires explicit virtual RAM load precheck")
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
    require(Set(2, 4).contains(lsuEntries), "FPGA-next LSU experiment uses two or four owners")
    require(Set(1, 2, 4).contains(dmaLineEntries) && (dmaLineTransfers || dmaLineEntries == 1))
    require(Set(0, 4, 8, 16, 32, 64).contains(dmaLineYieldCycles) && (dmaLineTransfers || dmaLineYieldCycles == 0))
    require(!precheckedDataRequestFlow || virtualRamLoadPrecheck,
        "prechecked flow is an explicit virtual-load-precheck experiment")
    val selectedTopology = optimized && independentFetchPayloadCapture && ownerLocalIssueReady &&
        sharedFetchPmpRelations && shareProtectedHeadPayload && bankedInstructionData
    val name = (if (selectedTopology) "fpga-next-selected-v2" else if (optimized)
        "fpga-next-storage-v1" else "fpga-next-reference-topology-v1") +
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
        (if (physicalLoadIngressFlow) "-physical-ingress-flow" else "") +
        (if (translatedResponseEmptyFlow) "-translated-response-empty-flow" else "") +
        (if (lsuEntries != 2) s"-lsu$lsuEntries" else "") +
        robEntries.map(n => s"-rob$n").getOrElse("") +
        physicalRegs.map(n => s"-prf$n").getOrElse("") +
        (if (loadOrderOlderRetire) "-older-load-retire" else "") +
        (if (fetchPreviousPacket) "-fetch-previous-packet" else "") +
        (if (preparedStoreLookahead) "-prepared-store-lookahead" else "") +
        (if (storeNextLinePrefetch) "-checked-store-prefetch" else "") +
        (if (storePrefetchMruInsertion) "-store-prefetch-mru" else "") +
        (if (storePrefetchLruVictim) "-store-prefetch-lru-victim" else "") +
        (if (postedStoreMerge) "-posted-store-merge" else "") +
        (if (postedPrefetchCoexistence) "-posted-prefetch-coexistence" else "") +
        (if (postedPrefetchHeadOffer) "-posted-prefetch-head-offer" else "") +
        (if (canonicalVirtualStoreOverlap) "-canonical-virtual-store-overlap" else "") +
        (if (memoryProofFrontier) "-memory-proof-frontier" else "") +
        (if (experimentalTriSpeedEthernet) "-experimental-trispeed" else "") +
        (if (dmaLineTransfers) "-dma-lines" else "") +
        (if (dmaLineEntries > 1) s"-owners${dmaLineEntries}" else "") +
        (if (dmaLineYieldCycles > 0) s"-yield${dmaLineYieldCycles}" else "")
    val interfaceVersion = 1
    val timingProfile = if (lsuEntries == 4) BoardSocConfig.memoryCapacityProfile else "staged-fetch-turnover"
    val isaProfile = "rv64gc"
    val issueWidth = 2
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
    val ddr = DdrBridgeConfig(maxOutstanding = 4, maxBurstBeats = 16, axiIdWidth = 4,
        maxOutstandingWrites = 2, unorderedResponses = true)
    val cache = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2,
        writebackEntries = 2, overlapWritebackRefill = true, nextLinePrefetch = true,
        prefetchCandidateCycles = prefetchCandidateCycles, prefetchBreakOnStore = prefetchBreakOnStore,
        storeNextLinePrefetch = storeNextLinePrefetch, storePrefetchMruInsertion = storePrefetchMruInsertion,
        postedPrefetchCoexistence = postedPrefetchCoexistence, storePrefetchLruVictim = storePrefetchLruVictim)
    val tags = CacheTagConfig(compact = true, bankedStorage = optimized)
    val floatingPointResources = if (optimized) FloatingPointResourceConfig.fpga else FloatingPointResourceConfig.baseline
    val storage = FpgaStorageConfig(bankedRobPayload = true, sharedStoreOperandReads = true,
        lvtPhysicalRegisterFile = true, bankedIssuePayload = optimized, bankedFetchHints = optimized,
        shareProtectedHeadPayload = shareProtectedHeadPayload)
    val network = NetworkDmaConfig(maxFrameBytes = 2048, macRxSlots = 4, postedRxSlots = 4,
        memoryCredits = 4, postedTxSlots = 4)
    val triSpeedTxFrameSlots = if (experimentalTriSpeedEthernet) 2 else 1
    val loadIssueForwarding = Some(true)
    val identityDataFlow = true
    // The registered two-word frontend already owns its instruction fetch window.
    // InstructionLineCache suppresses line prefetch in that profile.
    val instructionPrefetch = true

    def coreParams: OooParams = BoardSocConfig.boardParams(timingProfile, issueWidth,
        externalDdr = true, isa = isaProfile, ddrMemoryBytes = ddrBytes,
        loadIssueForwarding = loadIssueForwarding, identityDataFlow = identityDataFlow,
        fpgaStorage = storage, dataNextLinePrefetch = cache.nextLinePrefetch,
        dataStoreNextLinePrefetch = cache.storeNextLinePrefetch,
        virtualRamLoadPrecheck = virtualRamLoadPrecheck, floatingPointResources = floatingPointResources,
        independentFetchPayloadCapture = independentFetchPayloadCapture,
        ownerLocalIssueReady = ownerLocalIssueReady, sharedFetchPmpRelations = sharedFetchPmpRelations,
        precheckedDataRequestFlow = precheckedDataRequestFlow, physicalLoadIngressFlow = physicalLoadIngressFlow,
        translatedResponseEmptyFlow = translatedResponseEmptyFlow,
        loadOrderOlderRetire = loadOrderOlderRetire, fetchPreviousPacket = fetchPreviousPacket,
        preparedStoreLookahead = preparedStoreLookahead, postedStoreMerge = postedStoreMerge,
        postedPrefetchHeadOffer = postedPrefetchHeadOffer,
        canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap, memoryProofFrontier = memoryProofFrontier,
        backendCapacity = backendCapacity)

    def managedBoard(jtagRamDownload: Boolean = false): BoardSocTop = new BoardSocTop(
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
        ownerLocalIssueReady = ownerLocalIssueReady, sharedFetchPmpRelations = sharedFetchPmpRelations,
        bankedInstructionData = bankedInstructionData, jtagRamDownload = jtagRamDownload,
        dmaLineTransfers = dmaLineTransfers, dmaLineYieldCycles = dmaLineYieldCycles, dmaLineEntries = dmaLineEntries,
        precheckedDataRequestFlow = precheckedDataRequestFlow, physicalLoadIngressFlow = physicalLoadIngressFlow,
        translatedResponseEmptyFlow = translatedResponseEmptyFlow,
        loadOrderOlderRetire = loadOrderOlderRetire, fetchPreviousPacket = fetchPreviousPacket,
        preparedStoreLookahead = preparedStoreLookahead,
        dataTranslationEntries = dataTranslationEntries, postedStoreMerge = postedStoreMerge,
        postedPrefetchHeadOffer = postedPrefetchHeadOffer,
        canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap, memoryProofFrontier = memoryProofFrontier,
        backendCapacity = backendCapacity)
}

object FpgaNextConfig {
    val Reference = FpgaNextConfig()
    val Candidate = FpgaNextConfig(optimized = true)
    // Separately qualified timing experiment; the base candidate remains frozen.
    val FetchCaptureCandidate = Candidate.copy(independentFetchPayloadCapture = true)
    val TriSpeedCandidate = Candidate.copy(experimentalTriSpeedEthernet = true)
    val ControlCandidate = FetchCaptureCandidate.copy(ownerLocalIssueReady = true, sharedFetchPmpRelations = true)
    val Selected = ControlCandidate.copy(shareProtectedHeadPayload = true, bankedInstructionData = true)

    def fromOptions(options: Set[String], defaultSelected: Boolean): FpgaNextConfig = {
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
        base.copy(
            dataTranslationEntries = tlbCount,
            postedStoreMerge = options.contains("--posted-store-merge"),
            postedPrefetchCoexistence = options.contains("--posted-prefetch-coexistence"),
            postedPrefetchHeadOffer = options.contains("--posted-prefetch-head-offer"),
            canonicalVirtualStoreOverlap = options.contains("--canonical-virtual-store-overlap"),
            memoryProofFrontier = options.contains("--memory-proof-frontier"),
            lsuEntries = lsuCount, robEntries = robCount, physicalRegs = physicalCount,
            loadOrderOlderRetire = options.contains("--load-order-older-retire"),
            fetchPreviousPacket = options.contains("--fetch-previous-packet"),
            preparedStoreLookahead = options.contains("--prepared-store-lookahead"),
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
            virtualRamLoadPrecheck = options.contains("--virtual-ram-load-precheck"),
            experimentalTriSpeedEthernet = options.contains("--experimental-trispeed-ethernet"),
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
