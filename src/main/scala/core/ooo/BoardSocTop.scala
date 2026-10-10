package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.clock.{ClockManagementBoundary, ClockResource, ClockResourceControl, CmuParams}

/** Board-only memory map. Keep the small GSIM and module timing profiles unchanged. */
object BoardSocConfig {
    // Inventory only: existing domains stay protected until real endpoint
    // drain, isolation, wake and gate wiring have all been qualified together.
    def clockResources(aonHz: Int, cpuHz: Int, peripheralHz: Int, ddr: Boolean,
        ddrUiHz: Int, ethernet: Boolean): Seq[ClockResource] = Seq(
        ClockResource("AON", aonHz), ClockResource("CPU", cpuHz),
        ClockResource("TIME", cpuHz, parent = 1),
        ClockResource("UART", if (peripheralHz > 0) peripheralHz else cpuHz,
            parent = if (peripheralHz > 0) -1 else 1),
        ClockResource("DDR_UI", if (ddr) ddrUiHz else 0, present = ddr),
        ClockResource("GMAC_TX", if (ethernet) 125000000 else 0, present = ethernet),
        ClockResource("GMAC_RX", if (ethernet) 125000000 else 0, present = ethernet))
    val clockHz = 40000000
    val romBase = BigInt("80000000", 16)
    val romBytes = 128 * 1024
    val romWords = romBytes / 4
    val ramBase = BigInt("80200000", 16)
    val ramBytes = 1024 * 1024
    val ddrBytes: BigInt = BigInt(512) * 1024 * 1024
    val ddrBridge: DdrBridgeConfig = DdrBridgeConfig.Legacy
    val ramReadLatency = 3
    val dataCacheWays = 2
    val issueWidth = 2
    val isaProfile = "rv64imac"
    val isaProfiles = Set("rv64imac", "rv64imafc", "rv64gc")
    def usesStagedMemoryFabric(profile: String, p: OooParams): Boolean = Set("staged-fabric", "staged-control", "staged-data", "staged-execute", "staged-rename", "staged-retire", "staged-redirect", "staged-preparation", "staged-payload", "staged-return", "staged-fetch-address", "staged-fetch-control", "staged-recovery-control", "staged-execute-select", "staged-frontend-select", "staged-sensitive-paths", "staged-decode-align", "staged-rank-legality", "staged-word-destination", "staged-request-capture")
            .contains(profile) || p.registeredFabricBoundary
    def boardParams(profile: String, width: Int = issueWidth, externalDdr: Boolean = false,
        isa: String = isaProfile, ddrMemoryBytes: BigInt = ddrBytes,
        loadIssueForwarding: Option[Boolean] = None, identityDataFlow: Boolean = false,
        fpgaStorage: FpgaStorageConfig = FpgaStorageConfig.Registers, dataNextLinePrefetch: Boolean = false,
        dataStoreNextLinePrefetch: Boolean = false,
        virtualRamLoadPrecheck: Boolean = false,
        floatingPointResources: FloatingPointResourceConfig = FloatingPointResourceConfig.baseline,
        independentFetchPayloadCapture: Boolean = false, ownerLocalIssueReady: Boolean = false,
        sharedFetchPmpRelations: Boolean = false, precheckedDataRequestFlow: Boolean = false,
        physicalLoadIngressFlow: Boolean = false, loadOrderOlderRetire: Boolean = false,
        fetchPreviousPacket: Boolean = false, preparedStoreLookahead: Boolean = false,
        translatedResponseEmptyFlow: Boolean = false, postedStoreMerge: Boolean = false,
        postedPrefetchHeadOffer: Boolean = false, canonicalVirtualStoreOverlap: Boolean = false, memoryProofFrontier: Boolean = false,
        backendCapacity: BackendCapacityConfig = BackendCapacityConfig()): OooParams = {
        require(ddrMemoryBytes >= 4096 && ddrMemoryBytes <= (BigInt(1) << 31) && isPow2(ddrMemoryBytes))
        require(isaProfiles.contains(isa), s"Unknown board ISA profile: $isa")
        val fp = isa match {
            case "rv64imafc" => FloatingPointConfig.fullF
            case "rv64gc" => FloatingPointConfig.fullFD
            case _ => FloatingPointConfig.disabled
        }
        val timing = backendCapacity.configure(timingParams(profile, width))
        require(!virtualRamLoadPrecheck || usesStagedMemoryFabric(profile, timing),
            "virtual RAM load precheck requires a staged board fabric profile; choose it explicitly")
        fpgaStorage.configure(timing.copy(machineSystem = true, atomicMemory = true,
            preparedStoreLookahead = preparedStoreLookahead, postedStoreMerge = postedStoreMerge,
            postedPrefetchHeadOffer = postedPrefetchHeadOffer,
            canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap, memoryProofFrontier = memoryProofFrontier,
            translatedResponseEmptyFlow = translatedResponseEmptyFlow,
            registeredLoadIssueForwarding = loadIssueForwarding.getOrElse(timing.registeredLoadIssueForwarding),
            identityDataRequestFlow = identityDataFlow, dataNextLinePrefetch = dataNextLinePrefetch,
            dataStoreNextLinePrefetch = dataStoreNextLinePrefetch,
            virtualRamLoadPrecheck = virtualRamLoadPrecheck, precheckedDataRequestFlow = precheckedDataRequestFlow,
            physicalLoadIngressFlow = physicalLoadIngressFlow, loadOrderOlderRetire = loadOrderOlderRetire,
            independentFetchPayloadCapture = independentFetchPayloadCapture, fetchPreviousPacket = fetchPreviousPacket,
            ownerLocalIssueReady = ownerLocalIssueReady, sharedFetchPmpRelations = sharedFetchPmpRelations,
            pmpEntries = 16, virtualMemoryLevels = 3,
            speculativeRamBytes = if (externalDdr) ddrMemoryBytes else ramBytes,
            floatingPoint = fp.copy(resources = floatingPointResources), advertiseFloatingPoint = fp.f))
    }
    // Keep L1 response data flow-through; register physical owner metadata separately.
    val timingProfile = "early-issue"
    val memoryCapacityProfile = "staged-fetch-turnover-mlp4"
    val timingProfiles = Set(memoryCapacityProfile, "staged-fetch-turnover", "staged-load-issue", "staged-fetch-feedback", "staged-ethernet", "baseline", "early-issue", "queued-memory", "registered-response", "registered-replay",
        "staged-fabric", "staged-control", "staged-data", "staged-execute", "staged-rename", "staged-retire", "staged-redirect",
        "staged-preparation", "staged-payload", "staged-return", "staged-fetch-address", "staged-fetch-control",
        "staged-recovery-control", "staged-execute-select", "staged-frontend-select", "staged-sensitive-paths", "staged-decode-align", "staged-rank-legality", "staged-word-destination", "staged-request-capture", "staged-rom-boundary", "staged-control-heads", "staged-throughput", "staged-gmac-ready")
    def timingParams(profile: String, width: Int = issueWidth): OooParams = {
        require(timingProfiles.contains(profile), s"Unknown board timing profile: $profile")
        require(Set(2, 4).contains(width), s"Unsupported board issue width: $width")
        if (profile == memoryCapacityProfile) {
            require(width == 2, "memory capacity experiment retains two-issue baseline")
            return timingParams("staged-fetch-turnover", width).copy(memoryEntries = 4)
        }
        val loadIssueStage = profile == "staged-load-issue"
        val fetchTurnoverStage = profile == "staged-fetch-turnover"
        val fetchFeedbackStage = fetchTurnoverStage || loadIssueStage || profile == "staged-fetch-feedback"
        val ethernetStage = fetchFeedbackStage || profile == "staged-ethernet"
        val gmacReadyStage = ethernetStage || profile == "staged-gmac-ready"
        val throughputStage = gmacReadyStage || profile == "staged-throughput"
        val controlHeadsStage = throughputStage || profile == "staged-control-heads"
        val romBoundaryStage = controlHeadsStage || profile == "staged-rom-boundary"
        val requestCaptureStage = romBoundaryStage || profile == "staged-request-capture"
        val wordDestinationStage = requestCaptureStage || profile == "staged-word-destination"
        val rankLegalityStage = wordDestinationStage || profile == "staged-rank-legality"
        val decodeAlignStage = rankLegalityStage || profile == "staged-decode-align"
        val sensitivePathsStage = decodeAlignStage || profile == "staged-sensitive-paths"
        val frontendSelectStage = sensitivePathsStage || profile == "staged-frontend-select"
        val executeSelectStage = frontendSelectStage || profile == "staged-execute-select"
        val recoveryControlStage = executeSelectStage || profile == "staged-recovery-control"
        val fetchControlStage = recoveryControlStage || profile == "staged-fetch-control"
        val fetchAddressStage = fetchControlStage || profile == "staged-fetch-address"
        val returnStage = fetchAddressStage || profile == "staged-return"
        val payloadStage = returnStage || profile == "staged-payload"
        val preparationStage = payloadStage || profile == "staged-preparation"
        val redirectStage = preparationStage || profile == "staged-redirect"
        val retireStage = redirectStage || profile == "staged-retire"
        val renameStage = retireStage || profile == "staged-rename"
        val executeStage = renameStage || profile == "staged-execute"
        val dataStage = executeStage || profile == "staged-data"
        val controlStage = dataStage || profile == "staged-control"
        val fabricStage = controlStage || profile == "staged-fabric"
        // Width-only experiment: do not silently grow ROB/PRF/frontend caches for four-wide.
        params.copy(renameWidth = width, commitWidth = width, completionWidth = width,
            earlyRecoveryIssueBlock = profile != "baseline",
            registeredMemoryRequests = dataStage || profile == "queued-memory",
            registeredRobRetirement = fabricStage || profile == "registered-replay",
            registeredLoadReplay = fabricStage || profile == "registered-replay",
            precompleteMispredictedBranch = controlStage,
            parallelRenameAdmission = controlStage,
            stableFetchFaultMetadata = controlStage,
            earlyRankedOperands = executeStage,
            pcDerivedReturnLinks = executeStage,
            earlyRenameDestinations = renameStage,
            parallelPrfReadyUpdates = renameStage,
            stablePredictionMetadata = renameStage,
            balancedBranchCompare = retireStage && !redirectStage,
            separateBranchRetireFault = retireStage,
            parallelReturnStackControl = retireStage,
            earlyRedirectCapture = redirectStage,
            parallelMemoryPreparation = preparationStage,
            alignedFetchPmp = preparationStage,
            parallelIssuePayload = payloadStage, rawFetchPresence = payloadStage,
            oneHotPhysicalOperands = returnStage && !fetchAddressStage, registeredTranslatedResponses = returnStage,
            directMemoryResponse = returnStage, parallelFetchAddresses = fetchAddressStage,
            prefixTileLinkDecode = fetchAddressStage, rawTileLinkResponseMetadata = fetchControlStage,
            bufferedRomReplies = fetchControlStage, parallelPredictionQualification = fetchControlStage,
            parallelRecoveryAdmission = recoveryControlStage, parallelRedirectTokens = recoveryControlStage,
            parallelIssueRanks = executeSelectStage, parallelAluResults = executeSelectStage,
            parallelCompletionPayload = executeSelectStage,
            parallelFetchTagLookup = frontendSelectStage, parallelFrontendControl = frontendSelectStage,
            parallelAuipcQualification = frontendSelectStage,
            parallelPredictionSources = sensitivePathsStage, parallelAddressSums = sensitivePathsStage,
            bufferedFetchRequests = sensitivePathsStage, parallelFetchAlignment = decodeAlignStage,
            parallelDecodeLegality = decodeAlignStage, flowThroughFetchRequests = decodeAlignStage,
            parallelMinMaxResults = decodeAlignStage, parallelBitLegality = rankLegalityStage,
            parallelRenameRanks = rankLegalityStage, parallelMinMaxWordResults = rankLegalityStage,
            parallelArchitecturalDestinations = wordDestinationStage, parallelAluWordResults = wordDestinationStage,
            independentFetchCapture = requestCaptureStage, parallelHomeQualification = requestCaptureStage,
            registeredFabricBoundary = romBoundaryStage,
            registeredTranslationHeads = controlHeadsStage,
            fetchReplyTurnover = fetchTurnoverStage, fetchIdentityTranslation = fetchTurnoverStage,
            registeredPredictionTraining = controlHeadsStage,
            parallelMemoryPayload = controlHeadsStage, parallelPacketPmp = controlHeadsStage,
            registeredIssueExecute = throughputStage, registeredFetchPacket = throughputStage,
            registeredLoadIssueForwarding = loadIssueStage,
            wordSpanPacketPmp = gmacReadyStage, parallelFetchValidation = gmacReadyStage,
            fetchHintEntries = if (gmacReadyStage) 32 else 8,
            balancedPacketPmp = ethernetStage, compactMemoryOperandSelect = ethernetStage,
            parallelMemoryAddressSum = ethernetStage,
            capturedFetchPermission = fetchFeedbackStage, splitFetchCursor = fetchFeedbackStage,
            registeredFetchWindow = fetchFeedbackStage,
            fastHeadTrapRecovery = throughputStage, fastHeadSystemRecovery = throughputStage,
            tentativeRenameSources = throughputStage, sharedPhysicalSourceDecode = throughputStage,
            ownerLocalOperandReady = throughputStage,
            earlyStorePreparation = throughputStage, parallelMulDivDispatch = throughputStage,
            registeredMulDivOperands = throughputStage,
            registeredIssueHeadMask = fetchFeedbackStage,
            unconditionalMemoryPayloadCapture = fetchFeedbackStage)
    }
    def params: OooParams = OooParams(
        renameWidth = 2, commitWidth = 2, completionWidth = 2,
        robEntries = 16, physicalRegs = 48, memoryEntries = 2, branchPredictorEntries = 32,
        instructionCacheSets = 16, returnStackEntries = 8, storeBufferEntries = 2,
        registeredImsicInterrupts = true,
        speculativeRamBase = ramBase, speculativeRamBytes = ramBytes,
        bufferedRamStores = true, registeredBranchRedirect = true,
        registeredMemoryAddress = true, registeredStoreResponseOwners = true,
        recoveryWidth = 4, compressedInstructions = true)
}

/** Production ports: clock, reset, io_uartRx, io_uartTx. The board clock wizard and
  * reset synchronizer are outside this module. Simulation adds image-loading/debug
  * ports but uses the identical CPU, memory map and RAM response latency.
  */
class BoardSocTop(vivadoMemories: Boolean = true, simulation: Boolean = false,
    romFiles: Seq[String] = Seq.empty, socClockHz: Int = BoardSocConfig.clockHz,
    externalDdr: Boolean = false, timingProfile: String = BoardSocConfig.timingProfile,
    uartBaud: Int = 1500000, dataCacheWays: Int = BoardSocConfig.dataCacheWays,
    issueWidth: Int = BoardSocConfig.issueWidth, instructionPrefetch: Boolean = true,
    isaProfile: String = BoardSocConfig.isaProfile, peripheralClockHz: Int = 0,
    ethernetControl: Boolean = false, ethernetDma: Boolean = false,
    clockManagementHz: Int = 0, managedClockResources: Seq[ClockResource] = Seq.empty,
    ddrUiClockHz: Int = 250000000, managedPeripherals: Boolean = false,
    ddrMemoryBytes: BigInt = BoardSocConfig.ddrBytes, instructionLineCacheLines: Int = 8,
    dataCacheLines: Int = 32, ddrBridge: DdrBridgeConfig = BoardSocConfig.ddrBridge,
    cacheConcurrency: CoherentCacheConcurrency = CoherentCacheConcurrency(),
    loadIssueForwarding: Option[Boolean] = None,
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
    networkDmaConfig: soc.ip.dma.NetworkDmaConfig = soc.ip.dma.NetworkDmaConfig.Default,
    identityDataFlow: Boolean = false,
    fpgaStorage: FpgaStorageConfig = FpgaStorageConfig.Registers,
    virtualRamLoadPrecheck: Boolean = false,
    floatingPointResources: FloatingPointResourceConfig = FloatingPointResourceConfig.baseline,
    independentFetchPayloadCapture: Boolean = false,
    triSpeedEthernet: Boolean = false, triSpeedTxFrameSlots: Int = 1,
    ownerLocalIssueReady: Boolean = false, sharedFetchPmpRelations: Boolean = false,
    bankedInstructionData: Boolean = false, jtagRamDownload: Boolean = false,
    dmaLineTransfers: Boolean = false, dmaLineYieldCycles: Int = 0, dmaLineEntries: Int = 1,
    precheckedDataRequestFlow: Boolean = false, physicalLoadIngressFlow: Boolean = false,
    loadOrderOlderRetire: Boolean = false, fetchPreviousPacket: Boolean = false,
    preparedStoreLookahead: Boolean = false, dataTranslationEntries: Int = 8,
    translatedResponseEmptyFlow: Boolean = false, postedStoreMerge: Boolean = false,
    postedPrefetchHeadOffer: Boolean = false, canonicalVirtualStoreOverlap: Boolean = false, memoryProofFrontier: Boolean = false,
    backendCapacity: BackendCapacityConfig = BackendCapacityConfig()) extends Module {
    SvTranslationService.indexBits(dataTranslationEntries)
    if (externalDdr) ddrBridge.validateSoc()
    require(triSpeedTxFrameSlots == 1 || (triSpeedEthernet && triSpeedTxFrameSlots == 2))
    require(!triSpeedEthernet || managedPeripherals, "tri-speed media requires managed peripherals")
    require(dataCacheLines >= 4 && dataCacheLines <= 512 && isPow2(dataCacheLines),
        "board data cache lines must be a power of two in 4..512")
    require(instructionLineCacheLines >= 4 && instructionLineCacheLines <= 512 && isPow2(instructionLineCacheLines),
        "board instruction cache lines must be a power of two in 4..512")
    require(socClockHz >= 6000000)
    require(uartBaud > 0 && uartBaud.toLong * 16 <= socClockHz)
    require(!simulation || !vivadoMemories)
    require(!simulation || peripheralClockHz == 0, "independent clocks require CDC-only xsim verification")
    require(peripheralClockHz == 0 || uartBaud.toLong * 16 <= peripheralClockHz)
    require(!ethernetControl || (!simulation && peripheralClockHz > 0),
        "Ethernet control requires a production external peripheral clock")
    require(!ethernetDma || ethernetControl, "network DMA requires Ethernet control/domain configuration")
    require(clockManagementHz >= 0 && (clockManagementHz > 0 || managedClockResources.isEmpty))
    require(!simulation || clockManagementHz == 0, "independent CMU clocks require CDC-only verification")
    require(!managedPeripherals || (clockManagementHz > 0 && peripheralClockHz > 0 && ethernetControl &&
        ethernetDma && managedClockResources.isEmpty), "managed native UART/GMAC requires CMU and packet DMA")
    private val cmuConfig = if (clockManagementHz > 0) Some(CmuParams(clockManagementHz,
        BoardSocConfig.clockResources(clockManagementHz, socClockHz, peripheralClockHz,
            externalDdr, ddrUiClockHz, ethernetControl).zipWithIndex.map { case (resource, n) =>
            resource.copy(canGate = managedPeripherals && Set(3, 5, 6).contains(n))
        } ++ managedClockResources, timeoutCycles = if (managedPeripherals) 65536 else 1024)) else None
    private val memoryBytes = if (externalDdr) ddrMemoryBytes else BigInt(BoardSocConfig.ramBytes)
    private val p = BoardSocConfig.boardParams(timingProfile, issueWidth, externalDdr, isaProfile, ddrMemoryBytes,
        loadIssueForwarding = loadIssueForwarding, identityDataFlow = identityDataFlow, fpgaStorage = fpgaStorage,
        dataNextLinePrefetch = cacheConcurrency.nextLinePrefetch,
        dataStoreNextLinePrefetch = cacheConcurrency.storeNextLinePrefetch, virtualRamLoadPrecheck = virtualRamLoadPrecheck,
        floatingPointResources = floatingPointResources, independentFetchPayloadCapture = independentFetchPayloadCapture,
        ownerLocalIssueReady = ownerLocalIssueReady, sharedFetchPmpRelations = sharedFetchPmpRelations,
        precheckedDataRequestFlow = precheckedDataRequestFlow, physicalLoadIngressFlow = physicalLoadIngressFlow,
        translatedResponseEmptyFlow = translatedResponseEmptyFlow,
        loadOrderOlderRetire = loadOrderOlderRetire, fetchPreviousPacket = fetchPreviousPacket,
        preparedStoreLookahead = preparedStoreLookahead, postedStoreMerge = postedStoreMerge,
        postedPrefetchHeadOffer = postedPrefetchHeadOffer,
        canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap, memoryProofFrontier = memoryProofFrontier, backendCapacity = backendCapacity)
    require(!p.memoryProofFrontier || (dataCacheLines / dataCacheWays == p.memoryProofCacheSets && dataCacheWays == 2),
        "frontier PA set scheduling must match the actual cache geometry")
    // Internal composition ports stay outside the public BoardSocTop io bundle.
    val jtagDmi = if (jtagRamDownload) Some(IO(Flipped(new soc.ip.debug.DebugDmiPort(7)))) else None
    val jtagLinkUp = if (jtagRamDownload) Some(IO(Input(Bool()))) else None
    val io = IO(new Bundle {
        val peripheralClock = if (peripheralClockHz > 0) Some(Input(Clock())) else None
        val alwaysOnClock = cmuConfig.map(_ => Input(Clock()))
        val clockResources = if (managedClockResources.nonEmpty)
            Some(Vec(managedClockResources.size, new ClockResourceControl)) else None
        val ethernetAxi = if (ethernetControl && !managedPeripherals) Some(new soc.ip.axi.AxiLitePort) else None
        val ethernetIrq = if (ethernetControl && !managedPeripherals) Some(Input(Bool())) else None
        val ethernetReset = if (ethernetControl && !managedPeripherals) Some(Output(Bool())) else None
        val nativeGmac = if (managedPeripherals) Some(new Bundle {
            val triSpeedRgmii = if (triSpeedEthernet) Some(new soc.ip.ethernet.TriSpeedRgmiiPortV1) else None
            val rawTxClock = Input(Clock())
            val rawRxClock = Input(Clock())
            val rxData = Input(UInt(8.W))
            val rxValid = Input(Bool())
            val rxError = Input(Bool())
            val txData = Output(UInt(8.W))
            val txEnable = Output(Bool())
            val txError = Output(Bool())
            val linkUp = Input(Bool())
            val mdc = Output(Bool())
            val mdioIn = Input(Bool())
            val mdioOut = Output(Bool())
            val mdioOe = Output(Bool())
        }) else None
        val ethernetStreams = if (ethernetDma && !managedPeripherals) Some(new Bundle {
            val txData = Decoupled(new soc.ip.dma.EthernetAxisWord)
            val txControl = Decoupled(new soc.ip.dma.EthernetAxisWord)
            val rxData = Flipped(Decoupled(new soc.ip.dma.EthernetAxisWord))
            val rxStatus = Flipped(Decoupled(new soc.ip.dma.EthernetAxisWord))
        }) else None
        val ddrAxi = if (externalDdr) Some(new soc.ip.axi.Axi4MemoryPort(32, ddrBridge.axiIdWidth)) else None
        val ddrReady = if (externalDdr) Some(Input(Bool())) else None
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val program = if (simulation) Some(Input(new Bundle {
            val hold = Bool()
            val write = Bool()
            val index = UInt(log2Ceil(BoardSocConfig.romWords).W)
            val data = UInt(32.W)
        })) else None
        val ramProgram = if (simulation && !externalDdr) Some(Input(new Bundle {
            val write = Bool()
            val index = UInt(log2Ceil(BoardSocConfig.ramBytes / 8).W)
            val data = UInt(64.W)
        })) else None
        val commit = if (simulation) Some(Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))) else None
        val trap = if (simulation) Some(Output(Valid(new HeadException(p)))) else None
        val fetchPc = if (simulation) Some(Output(UInt(64.W))) else None
        val fetchWait = if (simulation) Some(Output(Bool())) else None
        val cacheProfile = if (simulation) Some(Output(new CoherentCacheProfile)) else None
        val headProfile = if (simulation) Some(Output(new HeadProfile)) else None
    })
    val platform = Module(new MachinePlatform(p, romWords = BoardSocConfig.romWords,
        romFiles = romFiles, programmable = simulation,
        tileLinkMemory = true, tileLinkFetch = true, ramBytes = memoryBytes,
        instructionLineCacheLines = instructionLineCacheLines, translationService = true, translationLevels = 3,
        coreDataTranslation = true, coreInstructionTranslation = true,
        coherentLineCache = true, coherentLineCacheLines = dataCacheLines, pteCacheEntries = 4,
        dataTranslationEntries = dataTranslationEntries,
        bufferCoherentResponses = true, vivadoMemories = vivadoMemories,
        ramReadLatency = BoardSocConfig.ramReadLatency,
        uartClockHz = socClockHz, uartFastDivisorOne = true, externalDdr = externalDdr,
        registerCoherentResponses = timingProfile == "registered-response", uartReferenceClockHz = uartBaud * 16,
        coherentLineCacheWays = dataCacheWays, instructionLineCachePrefetch = instructionPrefetch,
        registerPhysicalResponseOwners = true,
        stagedMemoryFabric = BoardSocConfig.usesStagedMemoryFabric(timingProfile, p),
        bufferTranslatedResponses = Set("staged-data", "staged-execute", "staged-rename", "staged-retire", "staged-redirect", "staged-preparation", "staged-payload", "staged-return", "staged-fetch-address", "staged-fetch-control", "staged-recovery-control", "staged-execute-select", "staged-frontend-select", "staged-sensitive-paths", "staged-decode-align", "staged-rank-legality", "staged-word-destination", "staged-request-capture")
            .contains(timingProfile) || p.registeredFabricBoundary, peripheralClockHz = peripheralClockHz,
        ethernetControl = ethernetControl, ethernetDma = ethernetDma, clockManagement = cmuConfig.nonEmpty,
        externalUart = managedPeripherals, ddrBridge = ddrBridge, cacheConcurrency = cacheConcurrency, tagConfig = tagConfig, networkDmaConfig = networkDmaConfig, bankedInstructionData = bankedInstructionData, jtagRamDownload = jtagRamDownload,
        dmaLineTransfers = dmaLineTransfers, dmaLineYieldCycles = dmaLineYieldCycles, dmaLineEntries = dmaLineEntries))
    jtagDmi.foreach { port => platform.io.jtagDmi.get <> port }
    jtagLinkUp.foreach { up => platform.io.jtagLinkUp.get := up }
    io.ethernetStreams.foreach { streams => streams <> platform.io.ethernetStreams.get }
    platform.io.peripheralClock.foreach(_ := io.peripheralClock.get)
    if (externalDdr) {
        io.ddrAxi.get <> platform.io.ddrAxi.get
        platform.io.ddrReady.get := io.ddrReady.get
    }
    platform.io.timerTick := true.B
    val nativeBank = if (managedPeripherals) {
        val bank = Module(new soc.ip.clock.ManagedPeripheralBank(cmuConfig.get, socClockHz,
            peripheralClockHz, uartBaud, networkDmaConfig = networkDmaConfig, triSpeedEthernet = triSpeedEthernet,
            triSpeedTxFrameSlots = triSpeedTxFrameSlots))
        bank.sourceClock := clock
        bank.alwaysOnClock := io.alwaysOnClock.get
        bank.rawUartClock := io.peripheralClock.get
        bank.rawTxClock := io.nativeGmac.get.rawTxClock
        bank.rawRxClock := io.nativeGmac.get.rawRxClock
        bank.commonReset := (reset.asBool || io.ddrReady.map(ready => !ready).getOrElse(false.B)).asAsyncReset
        bank.cmuRegisters <> platform.io.clockManagementRegisters.get
        bank.uartRegisters <> platform.io.externalUartRegisters.get
        platform.io.externalUartIrq.get := bank.uartIrq
        bank.gmacRegisters <> platform.io.ethernetRegisters.get
        bank.streams <> platform.io.ethernetStreams.get
        bank.uartRx := io.uartRx
        bank.gmiiRxData := io.nativeGmac.get.rxData
        bank.gmiiRxValid := io.nativeGmac.get.rxValid
        bank.gmiiRxError := io.nativeGmac.get.rxError
        bank.linkUp := io.nativeGmac.get.linkUp
        if (triSpeedEthernet) bank.triSpeedRgmii.get <> io.nativeGmac.get.triSpeedRgmii.get
        bank.mdioIn := io.nativeGmac.get.mdioIn
        io.nativeGmac.get.txData := bank.gmiiTxData
        io.nativeGmac.get.txEnable := bank.gmiiTxEnable
        io.nativeGmac.get.txError := bank.gmiiTxError
        io.nativeGmac.get.mdc := bank.mdc
        io.nativeGmac.get.mdioOut := bank.mdioOut
        io.nativeGmac.get.mdioOe := bank.mdioOe
        Some(bank)
    } else None
    val ethernetIrq = if (ethernetControl && !managedPeripherals) {
        val bridge = Module(new soc.ip.bus.RegisterClockDomainBridge)
        bridge.sourceClock := clock
        bridge.destinationClock := io.peripheralClock.get
        bridge.commonReset := (reset.asBool || io.ddrReady.map(ready => !ready).getOrElse(false.B)).asAsyncReset
        bridge.source <> platform.io.ethernetRegisters.get
        val adapter = withClockAndReset(io.peripheralClock.get, bridge.destinationReset) {
            Module(new soc.ip.axi.RegisterAxiLite(BigInt("10040000", 16), 0x40000))
        }
        adapter.io.registers <> bridge.destination
        io.ethernetAxi.get <> adapter.io.axi
        // Keep all Ethernet resets asserted for >=32 us at the configured
        // peripheral clock, covering 30 cycles even at the 10Mb/s MAC clock.
        val guardCycles = (peripheralClockHz.toLong * 32 / 1000000).toInt.max(1)
        val guardedReset = withClockAndReset(io.peripheralClock.get, bridge.destinationReset) {
            Module(new soc.ip.bus.ResetHold(guardCycles)).io.asserted
        }
        io.ethernetReset.get := guardedReset
        if (ethernetDma) {
            // Coordinated cold reset: CPU/DMA cannot enqueue a packet while the
            // MAC guard is clearing CDC FIFOs. Release locally on CPU clock.
            val cpuRelease = Module(new soc.ip.bus.CdcResetRelease)
            cpuRelease.clockIn := clock
            cpuRelease.asyncReset := (reset.asBool || guardedReset ||
                io.ddrReady.map(ready => !ready).getOrElse(false.B)).asAsyncReset
            // Preserve the existing synchronous CPU reset contract. The level
            // is asserted during cold reset and already released synchronously
            // on this clock; an AsyncReset here mixes inferred child resets.
            platform.reset := cpuRelease.resetOut.asBool
        }
        val irq = Module(new soc.ip.bus.CdcLevel)
        irq.clockIn := clock
        irq.resetIn := bridge.sourceReset
        irq.levelIn := io.ethernetIrq.get
        irq.levelOut
    } else nativeBank.map(_.gmacIrq).getOrElse(false.B)
    val cmuIrq = nativeBank.map(_.cmuIrq).getOrElse(cmuConfig.map { config =>
        val manager = Module(new ClockManagementBoundary(config))
        manager.sourceClock := clock
        manager.alwaysOnClock := io.alwaysOnClock.get
        manager.commonReset := (platform.reset.asBool ||
            io.ddrReady.map(ready => !ready).getOrElse(false.B)).asAsyncReset
        manager.registers <> platform.io.clockManagementRegisters.get
        for (n <- 0 until 7) {
            manager.resources(n).ack := false.B
            manager.resources(n).wake := false.B
        }
        for (n <- managedClockResources.indices) io.clockResources.get(n) <> manager.resources(n + 7)
        manager.irq
    }.getOrElse(false.B))
    // APLIC: UART=3, memcpy=4, MAC=5, packet DMA=6, optional CMU=7.
    platform.io.sources := (ethernetIrq.asUInt << 4) | (cmuIrq.asUInt << 6)
    platform.io.uartRx := io.uartRx
    platform.io.commitEnable := true.B
    platform.io.inspectRegister := 0.U
    platform.io.translationFlush.get := false.B
    io.uartTx := nativeBank.map(_.uartTx).getOrElse(platform.io.uartTx)
    if (simulation) {
        platform.io.program.get := io.program.get
        platform.io.ramProgram.foreach(_ := io.ramProgram.get)
        io.commit.get := platform.io.commit
        io.trap.get := platform.io.trap
        io.fetchPc.get := platform.io.fetchPc
        io.fetchWait.get := platform.io.fetchWait
        io.cacheProfile.get := platform.io.activity.get.coherentCacheProfile
        io.headProfile.get := platform.io.activity.get.headProfile
    }
}
