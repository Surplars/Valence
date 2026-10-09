package soc.core.ooo

import soc.ip.dma.NetworkDmaConfig

/** A versioned, fixed geometry for the independent FPGA-first integration.
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
    prefetchBreakOnStore: Boolean = false
) {
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
        (if (experimentalTriSpeedEthernet) "-experimental-trispeed" else "")
    val interfaceVersion = 1
    val timingProfile = "staged-fetch-turnover"
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
        prefetchCandidateCycles = prefetchCandidateCycles, prefetchBreakOnStore = prefetchBreakOnStore)
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
        virtualRamLoadPrecheck = virtualRamLoadPrecheck, floatingPointResources = floatingPointResources,
        independentFetchPayloadCapture = independentFetchPayloadCapture,
        ownerLocalIssueReady = ownerLocalIssueReady, sharedFetchPmpRelations = sharedFetchPmpRelations)

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
        bankedInstructionData = bankedInstructionData, jtagRamDownload = jtagRamDownload)
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
        base.copy(
            prefetchCandidateCycles = lifetime,
            prefetchBreakOnStore = options.contains("--prefetch-break-on-store"),
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
