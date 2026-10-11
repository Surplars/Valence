package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.core.ooo.{BoardSocConfig, BoardSocTop, DdrBridgeConfig, CoherentCacheConcurrency, CacheTagConfig, FpgaStorageConfig}

/** Avoid exposing a Vec at the GSIM top boundary (the pinned generator needs scalar accessors). */
class MemoryProofFrontierCpuGsim(externalDdr: Boolean = false, clockHz: Int = 40000000,
    timingProfile: String = BoardSocConfig.timingProfile, uartBaud: Int = 1500000,
    dataCacheWays: Int = BoardSocConfig.dataCacheWays,
    issueWidth: Int = BoardSocConfig.issueWidth, instructionPrefetch: Boolean = true,
    isaProfile: String = BoardSocConfig.isaProfile,
    ddrMemoryBytes: BigInt = BoardSocConfig.ddrBytes, frontendProbes: Boolean = false,
    instructionLineCacheLines: Int = 8, backendProbes: Boolean = false, dataCacheLines: Int = 32,
    ddrBridge: DdrBridgeConfig = BoardSocConfig.ddrBridge,
    cacheConcurrency: CoherentCacheConcurrency = CoherentCacheConcurrency(),
    loadIssueForwarding: Option[Boolean] = None,
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
    identityDataFlow: Boolean = false,
    fpgaStorage: FpgaStorageConfig = FpgaStorageConfig.Registers,
    virtualRamLoadPrecheck: Boolean = false,
    floatingPointResources: soc.core.ooo.FloatingPointResourceConfig = soc.core.ooo.FloatingPointResourceConfig.baseline,
    independentFetchPayloadCapture: Boolean = false,
    ownerLocalIssueReady: Boolean = false, sharedFetchPmpRelations: Boolean = false,
    bankedInstructionData: Boolean = false, dmaLineTransfers: Boolean = false,
    dmaLineYieldCycles: Int = 0, dmaLineEntries: Int = 1,
    precheckedDataRequestFlow: Boolean = false, physicalLoadIngressFlow: Boolean = false,
    loadOrderOlderRetire: Boolean = false, fetchPreviousPacket: Boolean = false,
    preparedStoreLookahead: Boolean = false, dataTranslationEntries: Int = 8,
    translatedResponseEmptyFlow: Boolean = false, postedStoreMerge: Boolean = false,
    lineageProfile: Option[soc.core.ooo.FpgaNextConfig] = None,
    postedPrefetchHeadOffer: Boolean = false, canonicalVirtualStoreOverlap: Boolean = false, memoryProofFrontier: Boolean = false, postedPreparationPriority: Boolean = false,
    backendCapacity: soc.core.ooo.BackendCapacityConfig = soc.core.ooo.BackendCapacityConfig()) extends Module {
    override def desiredName: String = "BoardSocGsim"
    private val board = Module(new BoardSocTop(vivadoMemories = false, simulation = true,
        externalDdr = externalDdr, socClockHz = clockHz, timingProfile = timingProfile, uartBaud = uartBaud,
        dataCacheWays = dataCacheWays, issueWidth = issueWidth, instructionPrefetch = instructionPrefetch,
        isaProfile = isaProfile, ddrMemoryBytes = ddrMemoryBytes, instructionLineCacheLines = instructionLineCacheLines,
        dataCacheLines = dataCacheLines, ddrBridge = ddrBridge, cacheConcurrency = cacheConcurrency, loadIssueForwarding = loadIssueForwarding, tagConfig = tagConfig, identityDataFlow = identityDataFlow, fpgaStorage = fpgaStorage,
        virtualRamLoadPrecheck = virtualRamLoadPrecheck, floatingPointResources = floatingPointResources,
        independentFetchPayloadCapture = independentFetchPayloadCapture,
        ownerLocalIssueReady = ownerLocalIssueReady, sharedFetchPmpRelations = sharedFetchPmpRelations,
        bankedInstructionData = bankedInstructionData, dmaLineTransfers = dmaLineTransfers, dmaLineYieldCycles = dmaLineYieldCycles, dmaLineEntries = dmaLineEntries,
        precheckedDataRequestFlow = precheckedDataRequestFlow, physicalLoadIngressFlow = physicalLoadIngressFlow,
        translatedResponseEmptyFlow = translatedResponseEmptyFlow,
        loadOrderOlderRetire = loadOrderOlderRetire, fetchPreviousPacket = fetchPreviousPacket,
        preparedStoreLookahead = preparedStoreLookahead,
        dataTranslationEntries = dataTranslationEntries, postedStoreMerge = postedStoreMerge,
        postedPrefetchHeadOffer = postedPrefetchHeadOffer,
        canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap, memoryProofFrontier = memoryProofFrontier, postedPreparationPriority = postedPreparationPriority, backendCapacity = backendCapacity))
    // Passive capacity evidence, derived from the actual final backend constructor.
    private val capacityBackend = board.platform.core.core.core.backend
    private def capacityTap[T <: Data](signal: T): T = BoringUtils.bore(signal)
    val capacityRobEntries = IO(Output(UInt(8.W)))
    capacityRobEntries := capacityBackend.p.robEntries.U
    val capacityRobBits = IO(Output(UInt(8.W)))
    capacityRobBits := capacityBackend.p.robBits.U
    val capacityPhysicalRegs = IO(Output(UInt(8.W)))
    capacityPhysicalRegs := capacityBackend.p.physicalRegs.U
    val capacityLsuEntries = IO(Output(UInt(8.W)))
    capacityLsuEntries := capacityBackend.p.memoryEntries.U
    val capacityRobOccupancy = IO(Output(UInt(8.W)))
    capacityRobOccupancy := capacityTap(capacityBackend.ledger.io.occupancy)
    val capacityFreePhysical = IO(Output(UInt(8.W)))
    capacityFreePhysical := capacityTap(capacityBackend.ledger.io.freeCount)
    val capacityDispatchReady = IO(Output(Bool()))
    capacityDispatchReady := capacityTap(capacityBackend.ledger.io.dispatchReady)
    val capacityRecovering = IO(Output(Bool()))
    capacityRecovering := capacityTap(capacityBackend.ledger.io.recovering)
    val capacityTagExhausted = IO(Output(Bool()))
    capacityTagExhausted := capacityTap(capacityBackend.ledger.io.tagExhausted)
    val capacityRenameOffer0 = IO(Output(Bool()))
    capacityRenameOffer0 := capacityTap(capacityBackend.ledger.io.allocate(0).valid)
    val capacityRenameWritesRd0 = IO(Output(Bool()))
    capacityRenameWritesRd0 := capacityTap(capacityBackend.ledger.io.allocate(0).bits.writesRd)
    val capacityRenameAccepted0 = IO(Output(Bool()))
    capacityRenameAccepted0 := capacityTap(capacityBackend.ledger.io.renamed(0).valid)
    val capacityRenameOffer1 = IO(Output(Bool()))
    capacityRenameOffer1 := capacityTap(capacityBackend.ledger.io.allocate(1).valid)
    val capacityRenameWritesRd1 = IO(Output(Bool()))
    capacityRenameWritesRd1 := capacityTap(capacityBackend.ledger.io.allocate(1).bits.writesRd)
    val capacityRenameAccepted1 = IO(Output(Bool()))
    capacityRenameAccepted1 := capacityTap(capacityBackend.ledger.io.renamed(1).valid)
    val capacityRenameFresh0 = IO(Output(Bool()))
    capacityRenameFresh0 := capacityTap(capacityBackend.ledger.freshRegisters(0))
    val capacityRegisterEnough0 = IO(Output(Bool()))
    capacityRegisterEnough0 := capacityTap(capacityBackend.ledger.faultCandidates.get.io.capacity)(0)
    val capacityRenameFresh1 = IO(Output(Bool()))
    capacityRenameFresh1 := capacityTap(capacityBackend.ledger.freshRegisters(1))
    val capacityRegisterEnough1 = IO(Output(Bool()))
    capacityRegisterEnough1 := capacityTap(capacityBackend.ledger.faultCandidates.get.io.capacity)(1)
    // Additional read-only frontier evidence. Never drives production inputs.
    val mpEnabled = IO(Output(Bool()))
    mpEnabled := memoryProofFrontier.B
    val mpEpoch = IO(Output(UInt(32.W)))
    mpEpoch := capacityTap(capacityBackend.io.loadPrecheck.get.epoch)
    val mpStable = IO(Output(Bool()))
    mpStable := capacityTap(capacityBackend.io.loadPrecheck.get.stable)
    val mpStartValid = IO(Output(Bool()))
    mpStartValid := capacityTap(capacityBackend.lsu.io.start.valid)
    val mpStartReady = IO(Output(Bool()))
    mpStartReady := capacityTap(capacityBackend.lsu.io.start.ready)
    val mpStartAccepted = IO(Output(Bool()))
    mpStartAccepted := capacityTap(capacityBackend.lsu.io.start.valid) && capacityTap(capacityBackend.lsu.io.start.ready)
    val mpStartIndex = IO(Output(UInt(6.W)))
    mpStartIndex := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.token.index), 0.U.asTypeOf(mpStartIndex))
    val mpStartTag = IO(Output(UInt(64.W)))
    mpStartTag := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.token.tag), 0.U.asTypeOf(mpStartTag))
    val mpStartEpoch = IO(Output(UInt(32.W)))
    mpStartEpoch := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.translationEpoch), 0.U.asTypeOf(mpStartEpoch))
    val mpStartVa = IO(Output(UInt(64.W)))
    mpStartVa := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.address), 0.U.asTypeOf(mpStartVa))
    val mpStartPa = IO(Output(UInt(64.W)))
    mpStartPa := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.physicalAddress), 0.U.asTypeOf(mpStartPa))
    val mpStartSize = IO(Output(UInt(3.W)))
    mpStartSize := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.size), 0.U.asTypeOf(mpStartSize))
    val mpStartStore = IO(Output(Bool()))
    mpStartStore := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.store), 0.U.asTypeOf(mpStartStore))
    val mpStartAtomic = IO(Output(Bool()))
    mpStartAtomic := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.atomic), 0.U.asTypeOf(mpStartAtomic))
    val mpStartPrechecked = IO(Output(Bool()))
    mpStartPrechecked := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.precheckedLoad), 0.U.asTypeOf(mpStartPrechecked))
    val mpStartParallel = IO(Output(Bool()))
    mpStartParallel := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.parallel), 0.U.asTypeOf(mpStartParallel))
    val mpStartSlot = IO(Output(UInt(2.W)))
    mpStartSlot := Mux(mpStartAccepted, capacityBackend.lsu.io.acceptedStartSlot.map(s => capacityTap(s.bits)).getOrElse(capacityTap(capacityBackend.lsu.chosen)), 0.U.asTypeOf(mpStartSlot))
    val mpStartFrontier = IO(Output(Bool()))
    mpStartFrontier := Mux(mpStartValid, capacityTap(capacityBackend.frontierChoice), 0.U.asTypeOf(mpStartFrontier))
    val mpStartIsHead = IO(Output(Bool()))
    mpStartIsHead := Mux(mpStartValid, capacityTap(capacityBackend.lsu.io.start.bits.token.index) === capacityTap(capacityBackend.head), 0.U.asTypeOf(mpStartIsHead))
    val mpReserved = IO(Output(UInt(5.W)))
    mpReserved := 0.U.asTypeOf(mpReserved)
    capacityBackend.proofFrontier.foreach { f => mpReserved := capacityTap(f.io.reservedCount) }
    val mpAllowed = IO(Output(UInt(5.W)))
    mpAllowed := 0.U.asTypeOf(mpAllowed)
    capacityBackend.proofFrontier.foreach { f => mpAllowed := capacityTap(f.io.allowedCount) }
    val mpBound = IO(Output(UInt(5.W)))
    mpBound := 0.U.asTypeOf(mpBound)
    capacityBackend.proofFrontier.foreach { f => mpBound := capacityTap(f.io.boundCount) }
    val mpScanState = IO(Output(UInt(2.W)))
    mpScanState := 0.U.asTypeOf(mpScanState)
    capacityBackend.proofFrontier.foreach { f => mpScanState := capacityTap(f.scanState) }
    val mpSnapshotLive = IO(Output(Bool()))
    mpSnapshotLive := 0.U.asTypeOf(mpSnapshotLive)
    capacityBackend.proofFrontier.foreach { f => mpSnapshotLive := capacityTap(f.snapshotLive) }
    val mpReadSelectedGrant = IO(Output(Bool()))
    mpReadSelectedGrant := 0.U.asTypeOf(mpReadSelectedGrant)
    capacityBackend.proofFrontier.foreach { f => mpReadSelectedGrant := capacityTap(f.selectedRead) }
    val mpReadCandidateGrant = IO(Output(Bool()))
    mpReadCandidateGrant := 0.U.asTypeOf(mpReadCandidateGrant)
    capacityBackend.proofFrontier.foreach { f => mpReadCandidateGrant := capacityTap(f.candidateRead) && !capacityTap(f.selectedRead) }
    val mpReadScanGrant = IO(Output(Bool()))
    mpReadScanGrant := 0.U.asTypeOf(mpReadScanGrant)
    capacityBackend.proofFrontier.foreach { f => mpReadScanGrant := capacityTap(f.scanRead) && !capacityTap(f.selectedRead) }
    val mpWriteGrant = IO(Output(Bool()))
    mpWriteGrant := 0.U.asTypeOf(mpWriteGrant)
    capacityBackend.proofFrontier.foreach { f => mpWriteGrant := capacityTap(f.positiveResult) && !capacityTap(f.removedRows)(capacityTap(f.resultRow)) }
    val mpEvict = IO(Output(Bool()))
    mpEvict := 0.U.asTypeOf(mpEvict)
    capacityBackend.proofFrontier.foreach { f => mpEvict := capacityTap(f.evict) }
    val mpClearMask = IO(Output(UInt(64.W)))
    mpClearMask := 0.U.asTypeOf(mpClearMask)
    capacityBackend.proofFrontier.foreach { f => mpClearMask := capacityTap(f.io.clearOwners) }
    val mpPause = IO(Output(Bool()))
    mpPause := 0.U.asTypeOf(mpPause)
    capacityBackend.proofFrontier.foreach { f => mpPause := capacityTap(f.io.pause) }
    val mpFlush = IO(Output(Bool()))
    mpFlush := 0.U.asTypeOf(mpFlush)
    capacityBackend.proofFrontier.foreach { f => mpFlush := capacityTap(f.io.flushQueries) }
    val mpAdmissionValid = IO(Output(Bool()))
    mpAdmissionValid := 0.U.asTypeOf(mpAdmissionValid)
    capacityBackend.proofFrontier.foreach { f => mpAdmissionValid := capacityTap(f.io.queryOwner.valid) }
    val mpAdmissionIndex = IO(Output(UInt(6.W)))
    mpAdmissionIndex := 0.U.asTypeOf(mpAdmissionIndex)
    capacityBackend.proofFrontier.foreach { f => mpAdmissionIndex := Mux(mpAdmissionValid, capacityTap(f.io.query.token.index), 0.U.asTypeOf(mpAdmissionIndex)) }
    val mpAdmissionTag = IO(Output(UInt(64.W)))
    mpAdmissionTag := 0.U.asTypeOf(mpAdmissionTag)
    capacityBackend.proofFrontier.foreach { f => mpAdmissionTag := Mux(mpAdmissionValid, capacityTap(f.io.query.token.tag), 0.U.asTypeOf(mpAdmissionTag)) }
    val mpAdmissionEpoch = IO(Output(UInt(32.W)))
    mpAdmissionEpoch := 0.U.asTypeOf(mpAdmissionEpoch)
    capacityBackend.proofFrontier.foreach { f => mpAdmissionEpoch := Mux(mpAdmissionValid, capacityTap(f.io.precheck.epoch), 0.U.asTypeOf(mpAdmissionEpoch)) }
    val mpAdmissionVa = IO(Output(UInt(64.W)))
    mpAdmissionVa := 0.U.asTypeOf(mpAdmissionVa)
    capacityBackend.proofFrontier.foreach { f => mpAdmissionVa := Mux(mpAdmissionValid, capacityTap(f.io.query.address), 0.U.asTypeOf(mpAdmissionVa)) }
    val mpAdmissionWrite = IO(Output(Bool()))
    mpAdmissionWrite := 0.U.asTypeOf(mpAdmissionWrite)
    capacityBackend.proofFrontier.foreach { f => mpAdmissionWrite := Mux(mpAdmissionValid, capacityTap(f.io.query.write), 0.U.asTypeOf(mpAdmissionWrite)) }
    val mpAdmissionSize = IO(Output(UInt(3.W)))
    mpAdmissionSize := 0.U.asTypeOf(mpAdmissionSize)
    capacityBackend.proofFrontier.foreach { f => mpAdmissionSize := Mux(mpAdmissionValid, capacityTap(f.io.query.size), 0.U.asTypeOf(mpAdmissionSize)) }
    val mpAdmissionRow = IO(Output(UInt(4.W)))
    mpAdmissionRow := 0.U.asTypeOf(mpAdmissionRow)
    capacityBackend.proofFrontier.foreach { f => mpAdmissionRow := Mux(mpAdmissionValid, capacityTap(f.admittedRow), 0.U.asTypeOf(mpAdmissionRow)) }
    val mpQueryValid = IO(Output(Bool()))
    mpQueryValid := 0.U.asTypeOf(mpQueryValid)
    capacityBackend.proofFrontier.foreach { f => mpQueryValid := capacityTap(f.io.precheck.request.valid) }
    val mpQueryIndex = IO(Output(UInt(6.W)))
    mpQueryIndex := 0.U.asTypeOf(mpQueryIndex)
    capacityBackend.proofFrontier.foreach { f => mpQueryIndex := Mux(mpQueryValid, capacityTap(f.addressProof.token.index), 0.U.asTypeOf(mpQueryIndex)) }
    val mpQueryTag = IO(Output(UInt(64.W)))
    mpQueryTag := 0.U.asTypeOf(mpQueryTag)
    capacityBackend.proofFrontier.foreach { f => mpQueryTag := Mux(mpQueryValid, capacityTap(f.addressProof.token.tag), 0.U.asTypeOf(mpQueryTag)) }
    val mpQueryEpoch = IO(Output(UInt(32.W)))
    mpQueryEpoch := 0.U.asTypeOf(mpQueryEpoch)
    capacityBackend.proofFrontier.foreach { f => mpQueryEpoch := Mux(mpQueryValid, capacityTap(f.addressProof.epoch), 0.U.asTypeOf(mpQueryEpoch)) }
    val mpQueryVa = IO(Output(UInt(64.W)))
    mpQueryVa := 0.U.asTypeOf(mpQueryVa)
    capacityBackend.proofFrontier.foreach { f => mpQueryVa := Mux(mpQueryValid, capacityTap(f.addressProof.payload.address), 0.U.asTypeOf(mpQueryVa)) }
    val mpQueryPa = IO(Output(UInt(64.W)))
    mpQueryPa := 0.U.asTypeOf(mpQueryPa)
    capacityBackend.proofFrontier.foreach { f => mpQueryPa := Mux(mpQueryValid, capacityTap(f.addressProof.payload.physicalAddress), 0.U.asTypeOf(mpQueryPa)) }
    val mpQueryWrite = IO(Output(Bool()))
    mpQueryWrite := 0.U.asTypeOf(mpQueryWrite)
    capacityBackend.proofFrontier.foreach { f => mpQueryWrite := Mux(mpQueryValid, capacityTap(f.addressProof.payload.write), 0.U.asTypeOf(mpQueryWrite)) }
    val mpQuerySize = IO(Output(UInt(3.W)))
    mpQuerySize := 0.U.asTypeOf(mpQuerySize)
    capacityBackend.proofFrontier.foreach { f => mpQuerySize := Mux(mpQueryValid, capacityTap(f.addressProof.payload.size), 0.U.asTypeOf(mpQuerySize)) }
    val mpQueryMask = IO(Output(UInt(8.W)))
    mpQueryMask := 0.U.asTypeOf(mpQueryMask)
    capacityBackend.proofFrontier.foreach { f => mpQueryMask := Mux(mpQueryValid, capacityTap(f.addressProof.payload.mask), 0.U.asTypeOf(mpQueryMask)) }
    val mpQueryRow = IO(Output(UInt(4.W)))
    mpQueryRow := 0.U.asTypeOf(mpQueryRow)
    capacityBackend.proofFrontier.foreach { f => mpQueryRow := Mux(mpQueryValid, capacityTap(f.addressRow), 0.U.asTypeOf(mpQueryRow)) }
    val mpResultValid = IO(Output(Bool()))
    mpResultValid := 0.U.asTypeOf(mpResultValid)
    capacityBackend.proofFrontier.foreach { f => mpResultValid := capacityTap(f.resultValid) }
    val mpResultIndex = IO(Output(UInt(6.W)))
    mpResultIndex := 0.U.asTypeOf(mpResultIndex)
    capacityBackend.proofFrontier.foreach { f => mpResultIndex := Mux(mpResultValid, capacityTap(f.resultProof.token.index), 0.U.asTypeOf(mpResultIndex)) }
    val mpResultTag = IO(Output(UInt(64.W)))
    mpResultTag := 0.U.asTypeOf(mpResultTag)
    capacityBackend.proofFrontier.foreach { f => mpResultTag := Mux(mpResultValid, capacityTap(f.resultProof.token.tag), 0.U.asTypeOf(mpResultTag)) }
    val mpResultEpoch = IO(Output(UInt(32.W)))
    mpResultEpoch := 0.U.asTypeOf(mpResultEpoch)
    capacityBackend.proofFrontier.foreach { f => mpResultEpoch := Mux(mpResultValid, capacityTap(f.resultProof.epoch), 0.U.asTypeOf(mpResultEpoch)) }
    val mpResultVa = IO(Output(UInt(64.W)))
    mpResultVa := 0.U.asTypeOf(mpResultVa)
    capacityBackend.proofFrontier.foreach { f => mpResultVa := Mux(mpResultValid, capacityTap(f.resultProof.payload.address), 0.U.asTypeOf(mpResultVa)) }
    val mpResultPa = IO(Output(UInt(64.W)))
    mpResultPa := 0.U.asTypeOf(mpResultPa)
    capacityBackend.proofFrontier.foreach { f => mpResultPa := Mux(mpResultValid, capacityTap(f.resultProof.payload.physicalAddress), 0.U.asTypeOf(mpResultPa)) }
    val mpResultWrite = IO(Output(Bool()))
    mpResultWrite := 0.U.asTypeOf(mpResultWrite)
    capacityBackend.proofFrontier.foreach { f => mpResultWrite := Mux(mpResultValid, capacityTap(f.resultProof.payload.write), 0.U.asTypeOf(mpResultWrite)) }
    val mpResultSize = IO(Output(UInt(3.W)))
    mpResultSize := 0.U.asTypeOf(mpResultSize)
    capacityBackend.proofFrontier.foreach { f => mpResultSize := Mux(mpResultValid, capacityTap(f.resultProof.payload.size), 0.U.asTypeOf(mpResultSize)) }
    val mpResultMask = IO(Output(UInt(8.W)))
    mpResultMask := 0.U.asTypeOf(mpResultMask)
    capacityBackend.proofFrontier.foreach { f => mpResultMask := Mux(mpResultValid, capacityTap(f.resultProof.payload.mask), 0.U.asTypeOf(mpResultMask)) }
    val mpResultRow = IO(Output(UInt(4.W)))
    mpResultRow := 0.U.asTypeOf(mpResultRow)
    capacityBackend.proofFrontier.foreach { f => mpResultRow := Mux(mpResultValid, capacityTap(f.resultRow), 0.U.asTypeOf(mpResultRow)) }
    val mpSelectedValid = IO(Output(Bool()))
    mpSelectedValid := 0.U.asTypeOf(mpSelectedValid)
    capacityBackend.proofFrontier.foreach { f => mpSelectedValid := capacityTap(f.io.selectedProof.valid) }
    val mpSelectedIndex = IO(Output(UInt(6.W)))
    mpSelectedIndex := 0.U.asTypeOf(mpSelectedIndex)
    capacityBackend.proofFrontier.foreach { f => mpSelectedIndex := Mux(mpSelectedValid, capacityTap(f.io.selectedProof.bits.token.index), 0.U.asTypeOf(mpSelectedIndex)) }
    val mpSelectedTag = IO(Output(UInt(64.W)))
    mpSelectedTag := 0.U.asTypeOf(mpSelectedTag)
    capacityBackend.proofFrontier.foreach { f => mpSelectedTag := Mux(mpSelectedValid, capacityTap(f.io.selectedProof.bits.token.tag), 0.U.asTypeOf(mpSelectedTag)) }
    val mpSelectedEpoch = IO(Output(UInt(32.W)))
    mpSelectedEpoch := 0.U.asTypeOf(mpSelectedEpoch)
    capacityBackend.proofFrontier.foreach { f => mpSelectedEpoch := Mux(mpSelectedValid, capacityTap(f.io.selectedProof.bits.epoch), 0.U.asTypeOf(mpSelectedEpoch)) }
    val mpSelectedVa = IO(Output(UInt(64.W)))
    mpSelectedVa := 0.U.asTypeOf(mpSelectedVa)
    capacityBackend.proofFrontier.foreach { f => mpSelectedVa := Mux(mpSelectedValid, capacityTap(f.io.selectedProof.bits.payload.address), 0.U.asTypeOf(mpSelectedVa)) }
    val mpSelectedPa = IO(Output(UInt(64.W)))
    mpSelectedPa := 0.U.asTypeOf(mpSelectedPa)
    capacityBackend.proofFrontier.foreach { f => mpSelectedPa := Mux(mpSelectedValid, capacityTap(f.io.selectedProof.bits.payload.physicalAddress), 0.U.asTypeOf(mpSelectedPa)) }
    val mpSelectedWrite = IO(Output(Bool()))
    mpSelectedWrite := 0.U.asTypeOf(mpSelectedWrite)
    capacityBackend.proofFrontier.foreach { f => mpSelectedWrite := Mux(mpSelectedValid, capacityTap(f.io.selectedProof.bits.payload.write), 0.U.asTypeOf(mpSelectedWrite)) }
    val mpSelectedSize = IO(Output(UInt(3.W)))
    mpSelectedSize := 0.U.asTypeOf(mpSelectedSize)
    capacityBackend.proofFrontier.foreach { f => mpSelectedSize := Mux(mpSelectedValid, capacityTap(f.io.selectedProof.bits.payload.size), 0.U.asTypeOf(mpSelectedSize)) }
    val mpSelectedMask = IO(Output(UInt(8.W)))
    mpSelectedMask := 0.U.asTypeOf(mpSelectedMask)
    capacityBackend.proofFrontier.foreach { f => mpSelectedMask := Mux(mpSelectedValid, capacityTap(f.io.selectedProof.bits.payload.mask), 0.U.asTypeOf(mpSelectedMask)) }
    val mpFrontierValid = IO(Output(Bool()))
    mpFrontierValid := 0.U.asTypeOf(mpFrontierValid)
    capacityBackend.proofFrontier.foreach { f => mpFrontierValid := capacityTap(f.io.frontier.valid) }
    val mpFrontierIndex = IO(Output(UInt(6.W)))
    mpFrontierIndex := 0.U.asTypeOf(mpFrontierIndex)
    capacityBackend.proofFrontier.foreach { f => mpFrontierIndex := Mux(mpFrontierValid, capacityTap(f.io.frontier.bits.token.index), 0.U.asTypeOf(mpFrontierIndex)) }
    val mpFrontierTag = IO(Output(UInt(64.W)))
    mpFrontierTag := 0.U.asTypeOf(mpFrontierTag)
    capacityBackend.proofFrontier.foreach { f => mpFrontierTag := Mux(mpFrontierValid, capacityTap(f.io.frontier.bits.token.tag), 0.U.asTypeOf(mpFrontierTag)) }
    val mpFrontierEpoch = IO(Output(UInt(32.W)))
    mpFrontierEpoch := 0.U.asTypeOf(mpFrontierEpoch)
    capacityBackend.proofFrontier.foreach { f => mpFrontierEpoch := Mux(mpFrontierValid, capacityTap(f.io.frontier.bits.epoch), 0.U.asTypeOf(mpFrontierEpoch)) }
    val mpFrontierVa = IO(Output(UInt(64.W)))
    mpFrontierVa := 0.U.asTypeOf(mpFrontierVa)
    capacityBackend.proofFrontier.foreach { f => mpFrontierVa := Mux(mpFrontierValid, capacityTap(f.io.frontier.bits.payload.address), 0.U.asTypeOf(mpFrontierVa)) }
    val mpFrontierPa = IO(Output(UInt(64.W)))
    mpFrontierPa := 0.U.asTypeOf(mpFrontierPa)
    capacityBackend.proofFrontier.foreach { f => mpFrontierPa := Mux(mpFrontierValid, capacityTap(f.io.frontier.bits.payload.physicalAddress), 0.U.asTypeOf(mpFrontierPa)) }
    val mpFrontierWrite = IO(Output(Bool()))
    mpFrontierWrite := 0.U.asTypeOf(mpFrontierWrite)
    capacityBackend.proofFrontier.foreach { f => mpFrontierWrite := Mux(mpFrontierValid, capacityTap(f.io.frontier.bits.payload.write), 0.U.asTypeOf(mpFrontierWrite)) }
    val mpFrontierSize = IO(Output(UInt(3.W)))
    mpFrontierSize := 0.U.asTypeOf(mpFrontierSize)
    capacityBackend.proofFrontier.foreach { f => mpFrontierSize := Mux(mpFrontierValid, capacityTap(f.io.frontier.bits.payload.size), 0.U.asTypeOf(mpFrontierSize)) }
    val mpFrontierMask = IO(Output(UInt(8.W)))
    mpFrontierMask := 0.U.asTypeOf(mpFrontierMask)
    capacityBackend.proofFrontier.foreach { f => mpFrontierMask := Mux(mpFrontierValid, capacityTap(f.io.frontier.bits.payload.mask), 0.U.asTypeOf(mpFrontierMask)) }
    val mpFrontierRow = IO(Output(UInt(4.W)))
    mpFrontierRow := 0.U.asTypeOf(mpFrontierRow)
    capacityBackend.proofFrontier.foreach { f => mpFrontierRow := Mux(mpFrontierValid, capacityTap(f.candidateRow), 0.U.asTypeOf(mpFrontierRow)) }
    val mpQueryHit = IO(Output(Bool()))
    mpQueryHit := 0.U.asTypeOf(mpQueryHit)
    capacityBackend.proofFrontier.foreach { f => mpQueryHit := Mux(mpQueryValid, capacityTap(f.io.precheck.response.valid), 0.U.asTypeOf(mpQueryHit)) }
    val mpQueryHitPa = IO(Output(UInt(64.W)))
    mpQueryHitPa := 0.U.asTypeOf(mpQueryHitPa)
    capacityBackend.proofFrontier.foreach { f => mpQueryHitPa := Mux(mpQueryHit, capacityTap(f.io.precheck.response.bits.physicalAddress), 0.U.asTypeOf(mpQueryHitPa)) }
    val mpQueryHitEpoch = IO(Output(UInt(32.W)))
    mpQueryHitEpoch := 0.U.asTypeOf(mpQueryHitEpoch)
    capacityBackend.proofFrontier.foreach { f => mpQueryHitEpoch := Mux(mpQueryHit, capacityTap(f.io.precheck.response.bits.epoch), 0.U.asTypeOf(mpQueryHitEpoch)) }
    val mpQueryHitPbmt = IO(Output(UInt(2.W)))
    mpQueryHitPbmt := 0.U.asTypeOf(mpQueryHitPbmt)
    capacityBackend.proofFrontier.foreach { f => mpQueryHitPbmt := Mux(mpQueryHit, capacityTap(f.io.precheck.response.bits.pbmt), 0.U.asTypeOf(mpQueryHitPbmt)) }
    val mpResultAllowed = IO(Output(Bool()))
    mpResultAllowed := 0.U.asTypeOf(mpResultAllowed)
    capacityBackend.proofFrontier.foreach { f => mpResultAllowed := Mux(mpResultValid, capacityTap(f.resultAllowed), 0.U.asTypeOf(mpResultAllowed)) }
    val mpResultOwnerMatches = IO(Output(Bool()))
    mpResultOwnerMatches := 0.U.asTypeOf(mpResultOwnerMatches)
    capacityBackend.proofFrontier.foreach { f => mpResultOwnerMatches := Mux(mpResultValid, capacityTap(f.resultMatches), 0.U.asTypeOf(mpResultOwnerMatches)) }
    val mpResultReservation = IO(Output(Bool()))
    mpResultReservation := 0.U.asTypeOf(mpResultReservation)
    capacityBackend.proofFrontier.foreach { f => mpResultReservation := Mux(mpResultValid, capacityTap(f.returningReservation), 0.U.asTypeOf(mpResultReservation)) }
    val mpResultInserted = IO(Output(Bool()))
    mpResultInserted := 0.U.asTypeOf(mpResultInserted)
    capacityBackend.proofFrontier.foreach { f => mpResultInserted := Mux(mpResultValid, capacityTap(f.positiveResult) && !capacityTap(f.removedRows)(capacityTap(f.resultRow)), 0.U.asTypeOf(mpResultInserted)) }
    val mpFrontierAccepted = IO(Output(Bool()))
    mpFrontierAccepted := 0.U.asTypeOf(mpFrontierAccepted)
    capacityBackend.proofFrontier.foreach { f => mpFrontierAccepted := capacityTap(f.io.frontierAccepted) }
    val mpFrontierCovered = IO(Output(UInt(64.W)))
    mpFrontierCovered := 0.U.asTypeOf(mpFrontierCovered)
    capacityBackend.proofFrontier.foreach { f => mpFrontierCovered := Mux(mpFrontierValid, capacityTap(f.covered), 0.U.asTypeOf(mpFrontierCovered)) }
    val mpFrontierRelied = IO(Output(UInt(16.W)))
    mpFrontierRelied := 0.U.asTypeOf(mpFrontierRelied)
    capacityBackend.proofFrontier.foreach { f => mpFrontierRelied := Mux(mpFrontierValid, capacityTap(f.relied), 0.U.asTypeOf(mpFrontierRelied)) }
    val mpRow0Valid = IO(Output(Bool()))
    mpRow0Valid := 0.U.asTypeOf(mpRow0Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow0Valid := capacityTap(f.state(0)) =/= 0.U }
    val mpRow0State = IO(Output(UInt(2.W)))
    mpRow0State := 0.U.asTypeOf(mpRow0State)
    capacityBackend.proofFrontier.foreach { f => mpRow0State := Mux(mpRow0Valid, capacityTap(f.state(0)), 0.U.asTypeOf(mpRow0State)) }
    val mpRow0Index = IO(Output(UInt(6.W)))
    mpRow0Index := 0.U.asTypeOf(mpRow0Index)
    capacityBackend.proofFrontier.foreach { f => mpRow0Index := Mux(mpRow0Valid, capacityTap(f.tokens(0).index), 0.U.asTypeOf(mpRow0Index)) }
    val mpRow0Tag = IO(Output(UInt(64.W)))
    mpRow0Tag := 0.U.asTypeOf(mpRow0Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow0Tag := Mux(mpRow0Valid, capacityTap(f.tokens(0).tag), 0.U.asTypeOf(mpRow0Tag)) }
    val mpRow0Epoch = IO(Output(UInt(32.W)))
    mpRow0Epoch := 0.U.asTypeOf(mpRow0Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow0Epoch := Mux(mpRow0Valid, capacityTap(f.epochs(0)), 0.U.asTypeOf(mpRow0Epoch)) }
    val mpRow0Bound = IO(Output(Bool()))
    mpRow0Bound := 0.U.asTypeOf(mpRow0Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow0Bound := Mux(mpRow0Valid, capacityTap(f.bound(0)), 0.U.asTypeOf(mpRow0Bound)) }
    val mpRow1Valid = IO(Output(Bool()))
    mpRow1Valid := 0.U.asTypeOf(mpRow1Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow1Valid := capacityTap(f.state(1)) =/= 0.U }
    val mpRow1State = IO(Output(UInt(2.W)))
    mpRow1State := 0.U.asTypeOf(mpRow1State)
    capacityBackend.proofFrontier.foreach { f => mpRow1State := Mux(mpRow1Valid, capacityTap(f.state(1)), 0.U.asTypeOf(mpRow1State)) }
    val mpRow1Index = IO(Output(UInt(6.W)))
    mpRow1Index := 0.U.asTypeOf(mpRow1Index)
    capacityBackend.proofFrontier.foreach { f => mpRow1Index := Mux(mpRow1Valid, capacityTap(f.tokens(1).index), 0.U.asTypeOf(mpRow1Index)) }
    val mpRow1Tag = IO(Output(UInt(64.W)))
    mpRow1Tag := 0.U.asTypeOf(mpRow1Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow1Tag := Mux(mpRow1Valid, capacityTap(f.tokens(1).tag), 0.U.asTypeOf(mpRow1Tag)) }
    val mpRow1Epoch = IO(Output(UInt(32.W)))
    mpRow1Epoch := 0.U.asTypeOf(mpRow1Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow1Epoch := Mux(mpRow1Valid, capacityTap(f.epochs(1)), 0.U.asTypeOf(mpRow1Epoch)) }
    val mpRow1Bound = IO(Output(Bool()))
    mpRow1Bound := 0.U.asTypeOf(mpRow1Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow1Bound := Mux(mpRow1Valid, capacityTap(f.bound(1)), 0.U.asTypeOf(mpRow1Bound)) }
    val mpRow2Valid = IO(Output(Bool()))
    mpRow2Valid := 0.U.asTypeOf(mpRow2Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow2Valid := capacityTap(f.state(2)) =/= 0.U }
    val mpRow2State = IO(Output(UInt(2.W)))
    mpRow2State := 0.U.asTypeOf(mpRow2State)
    capacityBackend.proofFrontier.foreach { f => mpRow2State := Mux(mpRow2Valid, capacityTap(f.state(2)), 0.U.asTypeOf(mpRow2State)) }
    val mpRow2Index = IO(Output(UInt(6.W)))
    mpRow2Index := 0.U.asTypeOf(mpRow2Index)
    capacityBackend.proofFrontier.foreach { f => mpRow2Index := Mux(mpRow2Valid, capacityTap(f.tokens(2).index), 0.U.asTypeOf(mpRow2Index)) }
    val mpRow2Tag = IO(Output(UInt(64.W)))
    mpRow2Tag := 0.U.asTypeOf(mpRow2Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow2Tag := Mux(mpRow2Valid, capacityTap(f.tokens(2).tag), 0.U.asTypeOf(mpRow2Tag)) }
    val mpRow2Epoch = IO(Output(UInt(32.W)))
    mpRow2Epoch := 0.U.asTypeOf(mpRow2Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow2Epoch := Mux(mpRow2Valid, capacityTap(f.epochs(2)), 0.U.asTypeOf(mpRow2Epoch)) }
    val mpRow2Bound = IO(Output(Bool()))
    mpRow2Bound := 0.U.asTypeOf(mpRow2Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow2Bound := Mux(mpRow2Valid, capacityTap(f.bound(2)), 0.U.asTypeOf(mpRow2Bound)) }
    val mpRow3Valid = IO(Output(Bool()))
    mpRow3Valid := 0.U.asTypeOf(mpRow3Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow3Valid := capacityTap(f.state(3)) =/= 0.U }
    val mpRow3State = IO(Output(UInt(2.W)))
    mpRow3State := 0.U.asTypeOf(mpRow3State)
    capacityBackend.proofFrontier.foreach { f => mpRow3State := Mux(mpRow3Valid, capacityTap(f.state(3)), 0.U.asTypeOf(mpRow3State)) }
    val mpRow3Index = IO(Output(UInt(6.W)))
    mpRow3Index := 0.U.asTypeOf(mpRow3Index)
    capacityBackend.proofFrontier.foreach { f => mpRow3Index := Mux(mpRow3Valid, capacityTap(f.tokens(3).index), 0.U.asTypeOf(mpRow3Index)) }
    val mpRow3Tag = IO(Output(UInt(64.W)))
    mpRow3Tag := 0.U.asTypeOf(mpRow3Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow3Tag := Mux(mpRow3Valid, capacityTap(f.tokens(3).tag), 0.U.asTypeOf(mpRow3Tag)) }
    val mpRow3Epoch = IO(Output(UInt(32.W)))
    mpRow3Epoch := 0.U.asTypeOf(mpRow3Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow3Epoch := Mux(mpRow3Valid, capacityTap(f.epochs(3)), 0.U.asTypeOf(mpRow3Epoch)) }
    val mpRow3Bound = IO(Output(Bool()))
    mpRow3Bound := 0.U.asTypeOf(mpRow3Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow3Bound := Mux(mpRow3Valid, capacityTap(f.bound(3)), 0.U.asTypeOf(mpRow3Bound)) }
    val mpRow4Valid = IO(Output(Bool()))
    mpRow4Valid := 0.U.asTypeOf(mpRow4Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow4Valid := capacityTap(f.state(4)) =/= 0.U }
    val mpRow4State = IO(Output(UInt(2.W)))
    mpRow4State := 0.U.asTypeOf(mpRow4State)
    capacityBackend.proofFrontier.foreach { f => mpRow4State := Mux(mpRow4Valid, capacityTap(f.state(4)), 0.U.asTypeOf(mpRow4State)) }
    val mpRow4Index = IO(Output(UInt(6.W)))
    mpRow4Index := 0.U.asTypeOf(mpRow4Index)
    capacityBackend.proofFrontier.foreach { f => mpRow4Index := Mux(mpRow4Valid, capacityTap(f.tokens(4).index), 0.U.asTypeOf(mpRow4Index)) }
    val mpRow4Tag = IO(Output(UInt(64.W)))
    mpRow4Tag := 0.U.asTypeOf(mpRow4Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow4Tag := Mux(mpRow4Valid, capacityTap(f.tokens(4).tag), 0.U.asTypeOf(mpRow4Tag)) }
    val mpRow4Epoch = IO(Output(UInt(32.W)))
    mpRow4Epoch := 0.U.asTypeOf(mpRow4Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow4Epoch := Mux(mpRow4Valid, capacityTap(f.epochs(4)), 0.U.asTypeOf(mpRow4Epoch)) }
    val mpRow4Bound = IO(Output(Bool()))
    mpRow4Bound := 0.U.asTypeOf(mpRow4Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow4Bound := Mux(mpRow4Valid, capacityTap(f.bound(4)), 0.U.asTypeOf(mpRow4Bound)) }
    val mpRow5Valid = IO(Output(Bool()))
    mpRow5Valid := 0.U.asTypeOf(mpRow5Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow5Valid := capacityTap(f.state(5)) =/= 0.U }
    val mpRow5State = IO(Output(UInt(2.W)))
    mpRow5State := 0.U.asTypeOf(mpRow5State)
    capacityBackend.proofFrontier.foreach { f => mpRow5State := Mux(mpRow5Valid, capacityTap(f.state(5)), 0.U.asTypeOf(mpRow5State)) }
    val mpRow5Index = IO(Output(UInt(6.W)))
    mpRow5Index := 0.U.asTypeOf(mpRow5Index)
    capacityBackend.proofFrontier.foreach { f => mpRow5Index := Mux(mpRow5Valid, capacityTap(f.tokens(5).index), 0.U.asTypeOf(mpRow5Index)) }
    val mpRow5Tag = IO(Output(UInt(64.W)))
    mpRow5Tag := 0.U.asTypeOf(mpRow5Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow5Tag := Mux(mpRow5Valid, capacityTap(f.tokens(5).tag), 0.U.asTypeOf(mpRow5Tag)) }
    val mpRow5Epoch = IO(Output(UInt(32.W)))
    mpRow5Epoch := 0.U.asTypeOf(mpRow5Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow5Epoch := Mux(mpRow5Valid, capacityTap(f.epochs(5)), 0.U.asTypeOf(mpRow5Epoch)) }
    val mpRow5Bound = IO(Output(Bool()))
    mpRow5Bound := 0.U.asTypeOf(mpRow5Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow5Bound := Mux(mpRow5Valid, capacityTap(f.bound(5)), 0.U.asTypeOf(mpRow5Bound)) }
    val mpRow6Valid = IO(Output(Bool()))
    mpRow6Valid := 0.U.asTypeOf(mpRow6Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow6Valid := capacityTap(f.state(6)) =/= 0.U }
    val mpRow6State = IO(Output(UInt(2.W)))
    mpRow6State := 0.U.asTypeOf(mpRow6State)
    capacityBackend.proofFrontier.foreach { f => mpRow6State := Mux(mpRow6Valid, capacityTap(f.state(6)), 0.U.asTypeOf(mpRow6State)) }
    val mpRow6Index = IO(Output(UInt(6.W)))
    mpRow6Index := 0.U.asTypeOf(mpRow6Index)
    capacityBackend.proofFrontier.foreach { f => mpRow6Index := Mux(mpRow6Valid, capacityTap(f.tokens(6).index), 0.U.asTypeOf(mpRow6Index)) }
    val mpRow6Tag = IO(Output(UInt(64.W)))
    mpRow6Tag := 0.U.asTypeOf(mpRow6Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow6Tag := Mux(mpRow6Valid, capacityTap(f.tokens(6).tag), 0.U.asTypeOf(mpRow6Tag)) }
    val mpRow6Epoch = IO(Output(UInt(32.W)))
    mpRow6Epoch := 0.U.asTypeOf(mpRow6Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow6Epoch := Mux(mpRow6Valid, capacityTap(f.epochs(6)), 0.U.asTypeOf(mpRow6Epoch)) }
    val mpRow6Bound = IO(Output(Bool()))
    mpRow6Bound := 0.U.asTypeOf(mpRow6Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow6Bound := Mux(mpRow6Valid, capacityTap(f.bound(6)), 0.U.asTypeOf(mpRow6Bound)) }
    val mpRow7Valid = IO(Output(Bool()))
    mpRow7Valid := 0.U.asTypeOf(mpRow7Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow7Valid := capacityTap(f.state(7)) =/= 0.U }
    val mpRow7State = IO(Output(UInt(2.W)))
    mpRow7State := 0.U.asTypeOf(mpRow7State)
    capacityBackend.proofFrontier.foreach { f => mpRow7State := Mux(mpRow7Valid, capacityTap(f.state(7)), 0.U.asTypeOf(mpRow7State)) }
    val mpRow7Index = IO(Output(UInt(6.W)))
    mpRow7Index := 0.U.asTypeOf(mpRow7Index)
    capacityBackend.proofFrontier.foreach { f => mpRow7Index := Mux(mpRow7Valid, capacityTap(f.tokens(7).index), 0.U.asTypeOf(mpRow7Index)) }
    val mpRow7Tag = IO(Output(UInt(64.W)))
    mpRow7Tag := 0.U.asTypeOf(mpRow7Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow7Tag := Mux(mpRow7Valid, capacityTap(f.tokens(7).tag), 0.U.asTypeOf(mpRow7Tag)) }
    val mpRow7Epoch = IO(Output(UInt(32.W)))
    mpRow7Epoch := 0.U.asTypeOf(mpRow7Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow7Epoch := Mux(mpRow7Valid, capacityTap(f.epochs(7)), 0.U.asTypeOf(mpRow7Epoch)) }
    val mpRow7Bound = IO(Output(Bool()))
    mpRow7Bound := 0.U.asTypeOf(mpRow7Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow7Bound := Mux(mpRow7Valid, capacityTap(f.bound(7)), 0.U.asTypeOf(mpRow7Bound)) }
    val mpRow8Valid = IO(Output(Bool()))
    mpRow8Valid := 0.U.asTypeOf(mpRow8Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow8Valid := capacityTap(f.state(8)) =/= 0.U }
    val mpRow8State = IO(Output(UInt(2.W)))
    mpRow8State := 0.U.asTypeOf(mpRow8State)
    capacityBackend.proofFrontier.foreach { f => mpRow8State := Mux(mpRow8Valid, capacityTap(f.state(8)), 0.U.asTypeOf(mpRow8State)) }
    val mpRow8Index = IO(Output(UInt(6.W)))
    mpRow8Index := 0.U.asTypeOf(mpRow8Index)
    capacityBackend.proofFrontier.foreach { f => mpRow8Index := Mux(mpRow8Valid, capacityTap(f.tokens(8).index), 0.U.asTypeOf(mpRow8Index)) }
    val mpRow8Tag = IO(Output(UInt(64.W)))
    mpRow8Tag := 0.U.asTypeOf(mpRow8Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow8Tag := Mux(mpRow8Valid, capacityTap(f.tokens(8).tag), 0.U.asTypeOf(mpRow8Tag)) }
    val mpRow8Epoch = IO(Output(UInt(32.W)))
    mpRow8Epoch := 0.U.asTypeOf(mpRow8Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow8Epoch := Mux(mpRow8Valid, capacityTap(f.epochs(8)), 0.U.asTypeOf(mpRow8Epoch)) }
    val mpRow8Bound = IO(Output(Bool()))
    mpRow8Bound := 0.U.asTypeOf(mpRow8Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow8Bound := Mux(mpRow8Valid, capacityTap(f.bound(8)), 0.U.asTypeOf(mpRow8Bound)) }
    val mpRow9Valid = IO(Output(Bool()))
    mpRow9Valid := 0.U.asTypeOf(mpRow9Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow9Valid := capacityTap(f.state(9)) =/= 0.U }
    val mpRow9State = IO(Output(UInt(2.W)))
    mpRow9State := 0.U.asTypeOf(mpRow9State)
    capacityBackend.proofFrontier.foreach { f => mpRow9State := Mux(mpRow9Valid, capacityTap(f.state(9)), 0.U.asTypeOf(mpRow9State)) }
    val mpRow9Index = IO(Output(UInt(6.W)))
    mpRow9Index := 0.U.asTypeOf(mpRow9Index)
    capacityBackend.proofFrontier.foreach { f => mpRow9Index := Mux(mpRow9Valid, capacityTap(f.tokens(9).index), 0.U.asTypeOf(mpRow9Index)) }
    val mpRow9Tag = IO(Output(UInt(64.W)))
    mpRow9Tag := 0.U.asTypeOf(mpRow9Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow9Tag := Mux(mpRow9Valid, capacityTap(f.tokens(9).tag), 0.U.asTypeOf(mpRow9Tag)) }
    val mpRow9Epoch = IO(Output(UInt(32.W)))
    mpRow9Epoch := 0.U.asTypeOf(mpRow9Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow9Epoch := Mux(mpRow9Valid, capacityTap(f.epochs(9)), 0.U.asTypeOf(mpRow9Epoch)) }
    val mpRow9Bound = IO(Output(Bool()))
    mpRow9Bound := 0.U.asTypeOf(mpRow9Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow9Bound := Mux(mpRow9Valid, capacityTap(f.bound(9)), 0.U.asTypeOf(mpRow9Bound)) }
    val mpRow10Valid = IO(Output(Bool()))
    mpRow10Valid := 0.U.asTypeOf(mpRow10Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow10Valid := capacityTap(f.state(10)) =/= 0.U }
    val mpRow10State = IO(Output(UInt(2.W)))
    mpRow10State := 0.U.asTypeOf(mpRow10State)
    capacityBackend.proofFrontier.foreach { f => mpRow10State := Mux(mpRow10Valid, capacityTap(f.state(10)), 0.U.asTypeOf(mpRow10State)) }
    val mpRow10Index = IO(Output(UInt(6.W)))
    mpRow10Index := 0.U.asTypeOf(mpRow10Index)
    capacityBackend.proofFrontier.foreach { f => mpRow10Index := Mux(mpRow10Valid, capacityTap(f.tokens(10).index), 0.U.asTypeOf(mpRow10Index)) }
    val mpRow10Tag = IO(Output(UInt(64.W)))
    mpRow10Tag := 0.U.asTypeOf(mpRow10Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow10Tag := Mux(mpRow10Valid, capacityTap(f.tokens(10).tag), 0.U.asTypeOf(mpRow10Tag)) }
    val mpRow10Epoch = IO(Output(UInt(32.W)))
    mpRow10Epoch := 0.U.asTypeOf(mpRow10Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow10Epoch := Mux(mpRow10Valid, capacityTap(f.epochs(10)), 0.U.asTypeOf(mpRow10Epoch)) }
    val mpRow10Bound = IO(Output(Bool()))
    mpRow10Bound := 0.U.asTypeOf(mpRow10Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow10Bound := Mux(mpRow10Valid, capacityTap(f.bound(10)), 0.U.asTypeOf(mpRow10Bound)) }
    val mpRow11Valid = IO(Output(Bool()))
    mpRow11Valid := 0.U.asTypeOf(mpRow11Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow11Valid := capacityTap(f.state(11)) =/= 0.U }
    val mpRow11State = IO(Output(UInt(2.W)))
    mpRow11State := 0.U.asTypeOf(mpRow11State)
    capacityBackend.proofFrontier.foreach { f => mpRow11State := Mux(mpRow11Valid, capacityTap(f.state(11)), 0.U.asTypeOf(mpRow11State)) }
    val mpRow11Index = IO(Output(UInt(6.W)))
    mpRow11Index := 0.U.asTypeOf(mpRow11Index)
    capacityBackend.proofFrontier.foreach { f => mpRow11Index := Mux(mpRow11Valid, capacityTap(f.tokens(11).index), 0.U.asTypeOf(mpRow11Index)) }
    val mpRow11Tag = IO(Output(UInt(64.W)))
    mpRow11Tag := 0.U.asTypeOf(mpRow11Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow11Tag := Mux(mpRow11Valid, capacityTap(f.tokens(11).tag), 0.U.asTypeOf(mpRow11Tag)) }
    val mpRow11Epoch = IO(Output(UInt(32.W)))
    mpRow11Epoch := 0.U.asTypeOf(mpRow11Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow11Epoch := Mux(mpRow11Valid, capacityTap(f.epochs(11)), 0.U.asTypeOf(mpRow11Epoch)) }
    val mpRow11Bound = IO(Output(Bool()))
    mpRow11Bound := 0.U.asTypeOf(mpRow11Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow11Bound := Mux(mpRow11Valid, capacityTap(f.bound(11)), 0.U.asTypeOf(mpRow11Bound)) }
    val mpRow12Valid = IO(Output(Bool()))
    mpRow12Valid := 0.U.asTypeOf(mpRow12Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow12Valid := capacityTap(f.state(12)) =/= 0.U }
    val mpRow12State = IO(Output(UInt(2.W)))
    mpRow12State := 0.U.asTypeOf(mpRow12State)
    capacityBackend.proofFrontier.foreach { f => mpRow12State := Mux(mpRow12Valid, capacityTap(f.state(12)), 0.U.asTypeOf(mpRow12State)) }
    val mpRow12Index = IO(Output(UInt(6.W)))
    mpRow12Index := 0.U.asTypeOf(mpRow12Index)
    capacityBackend.proofFrontier.foreach { f => mpRow12Index := Mux(mpRow12Valid, capacityTap(f.tokens(12).index), 0.U.asTypeOf(mpRow12Index)) }
    val mpRow12Tag = IO(Output(UInt(64.W)))
    mpRow12Tag := 0.U.asTypeOf(mpRow12Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow12Tag := Mux(mpRow12Valid, capacityTap(f.tokens(12).tag), 0.U.asTypeOf(mpRow12Tag)) }
    val mpRow12Epoch = IO(Output(UInt(32.W)))
    mpRow12Epoch := 0.U.asTypeOf(mpRow12Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow12Epoch := Mux(mpRow12Valid, capacityTap(f.epochs(12)), 0.U.asTypeOf(mpRow12Epoch)) }
    val mpRow12Bound = IO(Output(Bool()))
    mpRow12Bound := 0.U.asTypeOf(mpRow12Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow12Bound := Mux(mpRow12Valid, capacityTap(f.bound(12)), 0.U.asTypeOf(mpRow12Bound)) }
    val mpRow13Valid = IO(Output(Bool()))
    mpRow13Valid := 0.U.asTypeOf(mpRow13Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow13Valid := capacityTap(f.state(13)) =/= 0.U }
    val mpRow13State = IO(Output(UInt(2.W)))
    mpRow13State := 0.U.asTypeOf(mpRow13State)
    capacityBackend.proofFrontier.foreach { f => mpRow13State := Mux(mpRow13Valid, capacityTap(f.state(13)), 0.U.asTypeOf(mpRow13State)) }
    val mpRow13Index = IO(Output(UInt(6.W)))
    mpRow13Index := 0.U.asTypeOf(mpRow13Index)
    capacityBackend.proofFrontier.foreach { f => mpRow13Index := Mux(mpRow13Valid, capacityTap(f.tokens(13).index), 0.U.asTypeOf(mpRow13Index)) }
    val mpRow13Tag = IO(Output(UInt(64.W)))
    mpRow13Tag := 0.U.asTypeOf(mpRow13Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow13Tag := Mux(mpRow13Valid, capacityTap(f.tokens(13).tag), 0.U.asTypeOf(mpRow13Tag)) }
    val mpRow13Epoch = IO(Output(UInt(32.W)))
    mpRow13Epoch := 0.U.asTypeOf(mpRow13Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow13Epoch := Mux(mpRow13Valid, capacityTap(f.epochs(13)), 0.U.asTypeOf(mpRow13Epoch)) }
    val mpRow13Bound = IO(Output(Bool()))
    mpRow13Bound := 0.U.asTypeOf(mpRow13Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow13Bound := Mux(mpRow13Valid, capacityTap(f.bound(13)), 0.U.asTypeOf(mpRow13Bound)) }
    val mpRow14Valid = IO(Output(Bool()))
    mpRow14Valid := 0.U.asTypeOf(mpRow14Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow14Valid := capacityTap(f.state(14)) =/= 0.U }
    val mpRow14State = IO(Output(UInt(2.W)))
    mpRow14State := 0.U.asTypeOf(mpRow14State)
    capacityBackend.proofFrontier.foreach { f => mpRow14State := Mux(mpRow14Valid, capacityTap(f.state(14)), 0.U.asTypeOf(mpRow14State)) }
    val mpRow14Index = IO(Output(UInt(6.W)))
    mpRow14Index := 0.U.asTypeOf(mpRow14Index)
    capacityBackend.proofFrontier.foreach { f => mpRow14Index := Mux(mpRow14Valid, capacityTap(f.tokens(14).index), 0.U.asTypeOf(mpRow14Index)) }
    val mpRow14Tag = IO(Output(UInt(64.W)))
    mpRow14Tag := 0.U.asTypeOf(mpRow14Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow14Tag := Mux(mpRow14Valid, capacityTap(f.tokens(14).tag), 0.U.asTypeOf(mpRow14Tag)) }
    val mpRow14Epoch = IO(Output(UInt(32.W)))
    mpRow14Epoch := 0.U.asTypeOf(mpRow14Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow14Epoch := Mux(mpRow14Valid, capacityTap(f.epochs(14)), 0.U.asTypeOf(mpRow14Epoch)) }
    val mpRow14Bound = IO(Output(Bool()))
    mpRow14Bound := 0.U.asTypeOf(mpRow14Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow14Bound := Mux(mpRow14Valid, capacityTap(f.bound(14)), 0.U.asTypeOf(mpRow14Bound)) }
    val mpRow15Valid = IO(Output(Bool()))
    mpRow15Valid := 0.U.asTypeOf(mpRow15Valid)
    capacityBackend.proofFrontier.foreach { f => mpRow15Valid := capacityTap(f.state(15)) =/= 0.U }
    val mpRow15State = IO(Output(UInt(2.W)))
    mpRow15State := 0.U.asTypeOf(mpRow15State)
    capacityBackend.proofFrontier.foreach { f => mpRow15State := Mux(mpRow15Valid, capacityTap(f.state(15)), 0.U.asTypeOf(mpRow15State)) }
    val mpRow15Index = IO(Output(UInt(6.W)))
    mpRow15Index := 0.U.asTypeOf(mpRow15Index)
    capacityBackend.proofFrontier.foreach { f => mpRow15Index := Mux(mpRow15Valid, capacityTap(f.tokens(15).index), 0.U.asTypeOf(mpRow15Index)) }
    val mpRow15Tag = IO(Output(UInt(64.W)))
    mpRow15Tag := 0.U.asTypeOf(mpRow15Tag)
    capacityBackend.proofFrontier.foreach { f => mpRow15Tag := Mux(mpRow15Valid, capacityTap(f.tokens(15).tag), 0.U.asTypeOf(mpRow15Tag)) }
    val mpRow15Epoch = IO(Output(UInt(32.W)))
    mpRow15Epoch := 0.U.asTypeOf(mpRow15Epoch)
    capacityBackend.proofFrontier.foreach { f => mpRow15Epoch := Mux(mpRow15Valid, capacityTap(f.epochs(15)), 0.U.asTypeOf(mpRow15Epoch)) }
    val mpRow15Bound = IO(Output(Bool()))
    mpRow15Bound := 0.U.asTypeOf(mpRow15Bound)
    capacityBackend.proofFrontier.foreach { f => mpRow15Bound := Mux(mpRow15Valid, capacityTap(f.bound(15)), 0.U.asTypeOf(mpRow15Bound)) }
    val mpLine0Valid = IO(Output(Bool()))
    mpLine0Valid := 0.U.asTypeOf(mpLine0Valid)
    capacityBackend.proofFrontier.foreach { f => mpLine0Valid := capacityTap(f.io.liveLines(0).valid) }
    val mpLine0Index = IO(Output(UInt(6.W)))
    mpLine0Index := 0.U.asTypeOf(mpLine0Index)
    capacityBackend.proofFrontier.foreach { f => mpLine0Index := Mux(mpLine0Valid, capacityTap(f.io.liveLines(0).bits.token.index), 0.U.asTypeOf(mpLine0Index)) }
    val mpLine0Tag = IO(Output(UInt(64.W)))
    mpLine0Tag := 0.U.asTypeOf(mpLine0Tag)
    capacityBackend.proofFrontier.foreach { f => mpLine0Tag := Mux(mpLine0Valid, capacityTap(f.io.liveLines(0).bits.token.tag), 0.U.asTypeOf(mpLine0Tag)) }
    val mpLine0PaLine = IO(Output(UInt(64.W)))
    mpLine0PaLine := 0.U.asTypeOf(mpLine0PaLine)
    capacityBackend.proofFrontier.foreach { f => mpLine0PaLine := Mux(mpLine0Valid, Cat(capacityTap(f.io.liveLines(0).bits.line), 0.U(6.W)), 0.U.asTypeOf(mpLine0PaLine)) }
    val mpLine1Valid = IO(Output(Bool()))
    mpLine1Valid := 0.U.asTypeOf(mpLine1Valid)
    capacityBackend.proofFrontier.foreach { f => mpLine1Valid := capacityTap(f.io.liveLines(1).valid) }
    val mpLine1Index = IO(Output(UInt(6.W)))
    mpLine1Index := 0.U.asTypeOf(mpLine1Index)
    capacityBackend.proofFrontier.foreach { f => mpLine1Index := Mux(mpLine1Valid, capacityTap(f.io.liveLines(1).bits.token.index), 0.U.asTypeOf(mpLine1Index)) }
    val mpLine1Tag = IO(Output(UInt(64.W)))
    mpLine1Tag := 0.U.asTypeOf(mpLine1Tag)
    capacityBackend.proofFrontier.foreach { f => mpLine1Tag := Mux(mpLine1Valid, capacityTap(f.io.liveLines(1).bits.token.tag), 0.U.asTypeOf(mpLine1Tag)) }
    val mpLine1PaLine = IO(Output(UInt(64.W)))
    mpLine1PaLine := 0.U.asTypeOf(mpLine1PaLine)
    capacityBackend.proofFrontier.foreach { f => mpLine1PaLine := Mux(mpLine1Valid, Cat(capacityTap(f.io.liveLines(1).bits.line), 0.U(6.W)), 0.U.asTypeOf(mpLine1PaLine)) }
    val mpLine2Valid = IO(Output(Bool()))
    mpLine2Valid := 0.U.asTypeOf(mpLine2Valid)
    capacityBackend.proofFrontier.foreach { f => mpLine2Valid := capacityTap(f.io.liveLines(2).valid) }
    val mpLine2Index = IO(Output(UInt(6.W)))
    mpLine2Index := 0.U.asTypeOf(mpLine2Index)
    capacityBackend.proofFrontier.foreach { f => mpLine2Index := Mux(mpLine2Valid, capacityTap(f.io.liveLines(2).bits.token.index), 0.U.asTypeOf(mpLine2Index)) }
    val mpLine2Tag = IO(Output(UInt(64.W)))
    mpLine2Tag := 0.U.asTypeOf(mpLine2Tag)
    capacityBackend.proofFrontier.foreach { f => mpLine2Tag := Mux(mpLine2Valid, capacityTap(f.io.liveLines(2).bits.token.tag), 0.U.asTypeOf(mpLine2Tag)) }
    val mpLine2PaLine = IO(Output(UInt(64.W)))
    mpLine2PaLine := 0.U.asTypeOf(mpLine2PaLine)
    capacityBackend.proofFrontier.foreach { f => mpLine2PaLine := Mux(mpLine2Valid, Cat(capacityTap(f.io.liveLines(2).bits.line), 0.U(6.W)), 0.U.asTypeOf(mpLine2PaLine)) }
    val mpLine3Valid = IO(Output(Bool()))
    mpLine3Valid := 0.U.asTypeOf(mpLine3Valid)
    capacityBackend.proofFrontier.foreach { f => mpLine3Valid := capacityTap(f.io.liveLines(3).valid) }
    val mpLine3Index = IO(Output(UInt(6.W)))
    mpLine3Index := 0.U.asTypeOf(mpLine3Index)
    capacityBackend.proofFrontier.foreach { f => mpLine3Index := Mux(mpLine3Valid, capacityTap(f.io.liveLines(3).bits.token.index), 0.U.asTypeOf(mpLine3Index)) }
    val mpLine3Tag = IO(Output(UInt(64.W)))
    mpLine3Tag := 0.U.asTypeOf(mpLine3Tag)
    capacityBackend.proofFrontier.foreach { f => mpLine3Tag := Mux(mpLine3Valid, capacityTap(f.io.liveLines(3).bits.token.tag), 0.U.asTypeOf(mpLine3Tag)) }
    val mpLine3PaLine = IO(Output(UInt(64.W)))
    mpLine3PaLine := 0.U.asTypeOf(mpLine3PaLine)
    capacityBackend.proofFrontier.foreach { f => mpLine3PaLine := Mux(mpLine3Valid, Cat(capacityTap(f.io.liveLines(3).bits.line), 0.U(6.W)), 0.U.asTypeOf(mpLine3PaLine)) }
    private val mpCache = board.platform.privateCache.get.asInstanceOf[soc.core.ooo.NonBlockingCoherentLineCache]
    val mpPfAlloc = IO(Output(Bool()))
    mpPfAlloc := capacityTap(mpCache.observationStorePrefetch.allocated)
    val mpPfPa = IO(Output(UInt(64.W)))
    mpPfPa := Mux(mpPfAlloc, capacityTap(mpCache.observationStorePrefetch.allocatedAddress), 0.U.asTypeOf(mpPfPa))
    val mpPfSlot = IO(Output(UInt(2.W)))
    mpPfSlot := Mux(mpPfAlloc, capacityTap(mpCache.observationStorePrefetch.allocatedSlot), 0.U.asTypeOf(mpPfSlot))
    val mpDemandAlloc = IO(Output(Bool()))
    mpDemandAlloc := capacityTap(mpCache.observationStorePrefetch.demandAlloc)
    val mpDemandPa = IO(Output(UInt(64.W)))
    mpDemandPa := Mux(mpDemandAlloc, capacityTap(mpCache.observationStorePrefetch.demandAllocAddress), 0.U.asTypeOf(mpDemandPa))
    val mpDemandSlot = IO(Output(UInt(2.W)))
    mpDemandSlot := Mux(mpDemandAlloc, capacityTap(mpCache.observationStorePrefetch.demandAllocSlot), 0.U.asTypeOf(mpDemandSlot))
    val mpRefill = IO(Output(Bool()))
    mpRefill := capacityTap(mpCache.observationStorePrefetch.refill)
    val mpRefillPa = IO(Output(UInt(64.W)))
    mpRefillPa := Mux(mpRefill, capacityTap(mpCache.observationStorePrefetch.refillAddress), 0.U.asTypeOf(mpRefillPa))
    val mpRefillSlot = IO(Output(UInt(2.W)))
    mpRefillSlot := Mux(mpRefill, capacityTap(mpCache.observationStorePrefetch.refillSlot), 0.U.asTypeOf(mpRefillSlot))
    val mpRefillPrefetch = IO(Output(Bool()))
    mpRefillPrefetch := Mux(mpRefill, capacityTap(mpCache.observationStorePrefetch.refillPrefetch), 0.U.asTypeOf(mpRefillPrefetch))
    val mpMshrLive = IO(Output(UInt(2.W)))
    mpMshrLive := capacityTap(mpCache.observationStorePrefetch.mshrLiveMask)
    val mpMshrPrefetch = IO(Output(UInt(2.W)))
    mpMshrPrefetch := capacityTap(mpCache.observationStorePrefetch.mshrPrefetchMask)
    val mpTlAValid = IO(Output(Bool()))
    mpTlAValid := capacityTap(mpCache.io.tl.a.valid)
    val mpTlAReady = IO(Output(Bool()))
    mpTlAReady := capacityTap(mpCache.io.tl.a.ready)
    val mpTlAAddress = IO(Output(UInt(64.W)))
    mpTlAAddress := Mux(mpTlAValid, capacityTap(mpCache.io.tl.a.bits.address), 0.U.asTypeOf(mpTlAAddress))
    val mpTlASource = IO(Output(UInt(3.W)))
    mpTlASource := Mux(mpTlAValid, capacityTap(mpCache.io.tl.a.bits.source), 0.U.asTypeOf(mpTlASource))
    val mpTlAOpcode = IO(Output(UInt(3.W)))
    mpTlAOpcode := Mux(mpTlAValid, capacityTap(mpCache.io.tl.a.bits.opcode), 0.U.asTypeOf(mpTlAOpcode))
    val mpTlASize = IO(Output(UInt(3.W)))
    mpTlASize := Mux(mpTlAValid, capacityTap(mpCache.io.tl.a.bits.size), 0.U.asTypeOf(mpTlASize))
    val mpTlDValid = IO(Output(Bool()))
    mpTlDValid := capacityTap(mpCache.io.tl.d.valid)
    val mpTlDReady = IO(Output(Bool()))
    mpTlDReady := capacityTap(mpCache.io.tl.d.ready)
    val mpTlDSource = IO(Output(UInt(3.W)))
    mpTlDSource := Mux(mpTlDValid, capacityTap(mpCache.io.tl.d.bits.source), 0.U.asTypeOf(mpTlDSource))
    val mpTlDOpcode = IO(Output(UInt(3.W)))
    mpTlDOpcode := Mux(mpTlDValid, capacityTap(mpCache.io.tl.d.bits.opcode), 0.U.asTypeOf(mpTlDOpcode))
    val mpTlDSize = IO(Output(UInt(3.W)))
    mpTlDSize := Mux(mpTlDValid, capacityTap(mpCache.io.tl.d.bits.size), 0.U.asTypeOf(mpTlDSize))
    val mpOtherValid = IO(Output(Bool()))
    mpOtherValid := capacityTap(board.platform.homeUpstream.request.valid)
    val mpOtherReady = IO(Output(Bool()))
    mpOtherReady := capacityTap(board.platform.homeUpstream.request.ready)
    val mpOtherPa = IO(Output(UInt(64.W)))
    mpOtherPa := Mux(mpOtherValid, capacityTap(board.platform.homeUpstream.request.bits.address), 0.U.asTypeOf(mpOtherPa))
    val mpOtherSize = IO(Output(UInt(3.W)))
    mpOtherSize := Mux(mpOtherValid, capacityTap(board.platform.homeUpstream.request.bits.size), 0.U.asTypeOf(mpOtherSize))
    val mpOtherWrite = IO(Output(Bool()))
    mpOtherWrite := Mux(mpOtherValid, capacityTap(board.platform.homeUpstream.request.bits.write), 0.U.asTypeOf(mpOtherWrite))
    val mpOtherResponseValid = IO(Output(Bool()))
    mpOtherResponseValid := capacityTap(board.platform.homeUpstream.response.valid)
    val mpOtherResponseReady = IO(Output(Bool()))
    mpOtherResponseReady := capacityTap(board.platform.homeUpstream.response.ready)
    val mpFetchAccepted = IO(Output(Bool()))
    mpFetchAccepted := capacityTap(board.platform.io.activity.get.fetchGetFire)
    val mpFetchPa = IO(Output(UInt(64.W)))
    mpFetchPa := Mux(mpFetchAccepted, capacityTap(board.platform.io.activity.get.fetchGetAddress), 0.U.asTypeOf(mpFetchPa))
    val mpFetchSize = IO(Output(UInt(3.W)))
    mpFetchSize := Mux(mpFetchAccepted, capacityTap(board.platform.io.activity.get.fetchGetSize), 0.U.asTypeOf(mpFetchSize))
    // A test-only, passive scalar view of this exact Board instance. No inputs,
    // queues or control paths are inserted by the composition fixture.
    val lineage = lineageProfile.map { profile =>
        val result = IO(Output(new PostedBoardTrace(profile.coreParams.copy(canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap))))
        CanonicalOverlapPostedProbes.connect(result, board, profile)
        result
    }
    val canonical = IO(Output(new soc.core.ooo.CanonicalOverlapTrace(
        lineageProfile.get.coreParams.copy(canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap))))
    soc.core.ooo.MemoryProofFrontierCanonicalProbes.connect(canonical, board, lineageProfile.get.coreParams.copy(
        canonicalVirtualStoreOverlap = canonicalVirtualStoreOverlap))
    val io = IO(new Bundle {
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val program = Input(chiselTypeOf(board.io.program.get))
        val ramProgram = Input(new Bundle {
            val write = Bool()
            val index = UInt(17.W)
            val data = UInt(64.W)
        })
        val ddrReady = Input(Bool())
        val ddrAxi = if (externalDdr) Some(new soc.ip.axi.Axi4MemoryPort(32, ddrBridge.axiIdWidth)) else None
        val trap = Output(chiselTypeOf(board.io.trap.get))
        val commit0 = Output(Bool())
        val commit0Pc = Output(UInt(64.W))
        val commit1 = Output(Bool())
        val commit1Pc = Output(UInt(64.W))
        val fetchPc = Output(UInt(64.W))
        val cacheProfile = Output(new soc.core.ooo.CoherentCacheProfile)
        val headProfile = Output(new soc.core.ooo.HeadProfile)
    })
    board.io.uartRx := io.uartRx
    board.io.program.get := io.program
    board.io.ramProgram.foreach(_ := io.ramProgram)
    if (externalDdr) {
        board.io.ddrReady.get := io.ddrReady
        io.ddrAxi.get <> board.io.ddrAxi.get
    }
    io.uartTx := board.io.uartTx
    io.trap := board.io.trap.get
    io.commit0 := board.io.commit.get(0).valid
    io.commit0Pc := board.io.commit.get(0).bits.pc
    io.commit1 := board.io.commit.get(1).valid
    io.commit1Pc := board.io.commit.get(1).bits.pc
    io.fetchPc := board.io.fetchPc.get
    io.cacheProfile := board.io.cacheProfile.get
    io.headProfile := board.io.headProfile.get

    // Capacity experiment only: scalar leaf taps preserve production interfaces and avoid
    // dynamic BoringUtils vector reads in the pinned generator. Old ledgers stay two-slot.
    val memoryLiveSlots = IO(Output(UInt(4.W)))
    if (timingProfile == BoardSocConfig.memoryCapacityProfile) {
        val slots = board.platform.core.core.core.backend.lsu.slots
        memoryLiveSlots := PopCount(slots.map(slot => BoringUtils.bore(slot.io.busy)))
    } else {
        memoryLiveSlots := 0.U
    }

    // Passive performance accounting only. Each field comes from an existing
    // production event; this adds no flow-control or architectural state.
    val dataPrefetchOriginEvents = IO(Output(UInt(6.W)))
    dataPrefetchOriginEvents := 0.U
    if (backendProbes && board.platform.privateCache.nonEmpty) {
        board.platform.privateCache.get match {
            case cache: soc.core.ooo.NonBlockingCoherentLineCache =>
                val observed = cache.observationStorePrefetch
                val candidate = BoringUtils.bore(observed.candidate)
                val candidateStore = BoringUtils.bore(observed.candidateStore)
                val allocated = BoringUtils.bore(observed.allocated)
                val allocatedStore = BoringUtils.bore(observed.allocatedStore)
                val useful = BoringUtils.bore(observed.useful)
                val usefulStore = BoringUtils.bore(observed.usefulStore)
                dataPrefetchOriginEvents := VecInit(Seq(
                    candidate && !candidateStore, candidate && candidateStore,
                    allocated && !allocatedStore, allocated && allocatedStore,
                    useful && !usefulStore, useful && usefulStore)).asUInt
            case _ =>
        }
    }
    val dataPrefetchEvents = IO(Output(UInt(11.W)))
    if (backendProbes && board.platform.privateCache.nonEmpty) {
        val cache = board.platform.privateCache.get
        dataPrefetchEvents := Cat(BoringUtils.bore(cache.io.prefetch.releaseOwners),
            BoringUtils.bore(cache.io.prefetch.missOwners), VecInit(Seq(
                BoringUtils.bore(cache.io.prefetch.candidate),
                BoringUtils.bore(cache.io.prefetch.allocated),
                BoringUtils.bore(cache.io.prefetch.useful),
                BoringUtils.bore(cache.io.prefetch.error),
                BoringUtils.bore(cache.io.prefetchBusy))).asUInt)
    } else { dataPrefetchEvents := 0.U }

    // Optional passive owner-qualified backend probes. Index and 64-bit tag remain separate.
    val backendEvents = IO(Output(UInt(48.W)))
    val backendHeadTag = IO(Output(UInt(64.W)))
    val backendHeadIndex = IO(Output(UInt(8.W)))
    val backendQueueHeadIndex = IO(Output(UInt(8.W)))
    val backendQueueHeadTag = IO(Output(UInt(64.W)))
    val backendRequestTag = IO(Output(UInt(64.W)))
    val backendRequestIndex = IO(Output(UInt(8.W)))
    val backendStartTag = IO(Output(UInt(64.W)))
    val backendStartIndex = IO(Output(UInt(8.W)))
    val backendCompleteTag = IO(Output(UInt(64.W)))
    val backendCompleteIndex = IO(Output(UInt(8.W)))
    val backendSlot0Tag = IO(Output(UInt(64.W)))
    val backendSlot1Tag = IO(Output(UInt(64.W)))
    // Upper-pair passive ABI leaves the historical lower pair unchanged.
    val backendSlot2Tag = IO(Output(UInt(64.W)))
    val backendSlot3Tag = IO(Output(UInt(64.W)))
    val backendSlotIndicesHi = IO(Output(UInt(16.W)))
    val backendSlotStateHi = IO(Output(UInt(16.W)))
    val backendSlotCount = IO(Output(UInt(8.W)))
    val backendSlotIndices = IO(Output(UInt(16.W)))
    val backendSlotState = IO(Output(UInt(16.W)))
    val backendReturnSlot = IO(Output(UInt(2.W)))
    val backendFifoCount = IO(Output(UInt(4.W)))
    val backendStoreCause = IO(Output(UInt(3.W)))
    val backendReset = IO(Output(Bool()))
    // Full scalar fingerprints for passive physical data-path ownership, never dynamic vector taps.
    val dataPathEvents = IO(Output(UInt(48.W)))
    // Optional bandwidth-experiment provenance. The legacy dataPath ABI stays
    // intact; these taps include the authorization fields it predates.
    val cpuFlowEvents = IO(Output(UInt(8.W)))
    val cpuFlowIngressAuth = IO(Output(UInt(64.W)))
    val cpuFlowCheckedAuth = IO(Output(UInt(64.W)))
    val cpuFlowCheckedAddress = IO(Output(UInt(64.W)))
    val cpuFlowCheckedData = IO(Output(UInt(64.W)))
    val cpuFlowCheckedHeadAuth = IO(Output(UInt(64.W)))
    val cpuFlowPhysicalAuth = IO(Output(UInt(64.W)))
    val dataPathCounts = IO(Output(UInt(64.W)))
    val dataPathRequest0Address = IO(Output(UInt(64.W)))
    val dataPathRequest0Data = IO(Output(UInt(64.W)))
    val dataPathRequest0Meta = IO(Output(UInt(64.W)))
    val dataPathRequest1Address = IO(Output(UInt(64.W)))
    val dataPathRequest1Data = IO(Output(UInt(64.W)))
    val dataPathRequest1Meta = IO(Output(UInt(64.W)))
    val dataPathRequest2Address = IO(Output(UInt(64.W)))
    val dataPathRequest2Data = IO(Output(UInt(64.W)))
    val dataPathRequest2Meta = IO(Output(UInt(64.W)))
    val dataPathRequest3Address = IO(Output(UInt(64.W)))
    val dataPathRequest3Data = IO(Output(UInt(64.W)))
    val dataPathRequest3Meta = IO(Output(UInt(64.W)))
    val dataPathRequest4Address = IO(Output(UInt(64.W)))
    val dataPathRequest4Data = IO(Output(UInt(64.W)))
    val dataPathRequest4Meta = IO(Output(UInt(64.W)))
    val dataPathRequest5Address = IO(Output(UInt(64.W)))
    val dataPathRequest5Data = IO(Output(UInt(64.W)))
    val dataPathRequest5Meta = IO(Output(UInt(64.W)))
    val dataPathRequest6Address = IO(Output(UInt(64.W)))
    val dataPathRequest6Data = IO(Output(UInt(64.W)))
    val dataPathRequest6Meta = IO(Output(UInt(64.W)))
    val dataPathRequest7Address = IO(Output(UInt(64.W)))
    val dataPathRequest7Data = IO(Output(UInt(64.W)))
    val dataPathRequest7Meta = IO(Output(UInt(64.W)))
    val dataPathRequest8Address = IO(Output(UInt(64.W)))
    val dataPathRequest8Data = IO(Output(UInt(64.W)))
    val dataPathRequest8Meta = IO(Output(UInt(64.W)))
    val dataPathRequest9Address = IO(Output(UInt(64.W)))
    val dataPathRequest9Data = IO(Output(UInt(64.W)))
    val dataPathRequest9Meta = IO(Output(UInt(64.W)))
    val dataPathReply0Data = IO(Output(UInt(64.W)))
    val dataPathReply0Flags = IO(Output(UInt(64.W)))
    val dataPathReply1Data = IO(Output(UInt(64.W)))
    val dataPathReply1Flags = IO(Output(UInt(64.W)))
    val dataPathReply2Data = IO(Output(UInt(64.W)))
    val dataPathReply2Flags = IO(Output(UInt(64.W)))
    val dataPathReply3Data = IO(Output(UInt(64.W)))
    val dataPathReply3Flags = IO(Output(UInt(64.W)))
    val dataPathReply4Data = IO(Output(UInt(64.W)))
    val dataPathReply4Flags = IO(Output(UInt(64.W)))
    backendReset := reset.asBool
    backendSlotCount := BoardSocConfig.timingParams(timingProfile, issueWidth).memoryEntries.U
    if (backendProbes) {
        require(frontendProbes && issueWidth == 2)
        val b = board.platform.core.core.core.backend
        val l = b.lsu
        val q = b.observationRequests.get
        val stores = b.observationStores.get
        require(Set(2, 4).contains(l.slots.size), "backend probes require two or four LSU owners")
        def tap[T <: Data](signal: T): T = BoringUtils.bore(signal)
        val h = tap(b.head)
        // Static scalar taps avoid dynamic-array output aliases in the pinned GSIM graph pass.
        def atHead(bits: Seq[Bool]): Bool = Mux1H(bits.zipWithIndex.map { case (bit, i) => (h === i.U) -> bit })
        val memoryReady1 = atHead((0 until b.p.robEntries).map(i => tap(b.ownerReady.get.io.ready1(i))))
        val memoryReady2 = atHead((0 until b.p.robEntries).map(i => tap(b.ownerReady.get.io.ready2(i))))
        val store = tap(b.headRequest.store)
        val atomic = tap(b.headRequest.atomic)
        val saved = atHead((0 until b.p.robEntries).map(i => tap(b.storePrepared(i))))
        val choiceHead = tap(b.memoryChoice.valid) && tap(b.memoryChoice.index) === h
        val headToken = b.ledger.io.headSystem.get.headToken
        backendHeadTag := tap(headToken.tag)
        backendHeadIndex := tap(headToken.index)
        backendQueueHeadTag := tap(b.headRenamed.token.tag)
        backendQueueHeadIndex := tap(b.headRenamed.token.index)
        backendRequestTag := tap(l.io.requestOwner.bits.tag)
        backendRequestIndex := tap(l.io.requestOwner.bits.index)
        backendStartTag := tap(l.io.start.bits.token.tag)
        backendStartIndex := tap(l.io.start.bits.token.index)
        backendCompleteTag := tap(l.io.complete.bits.token.tag)
        backendCompleteIndex := tap(l.io.complete.bits.token.index)
        backendSlot0Tag := tap(l.io.owner(0).tag)
        backendSlot1Tag := tap(l.io.owner(1).tag)
        backendSlotIndices := Cat(tap(l.io.owner(1).index).pad(8), tap(l.io.owner(0).index).pad(8))
        def slotPairState(first: Int): UInt = Cat(0.U(6.W),
            tap(l.io.cancel(first + 1)), tap(l.io.cancel(first)),
            tap(l.parallel(first + 1)), tap(l.parallel(first)),
            tap(l.io.phase(first + 1)), tap(l.io.phase(first)),
            tap(l.io.live(first + 1)), tap(l.io.live(first)))
        backendSlotState := slotPairState(0)
        if (l.slots.size == 4) {
            backendSlot2Tag := tap(l.io.owner(2).tag)
            backendSlot3Tag := tap(l.io.owner(3).tag)
            backendSlotIndicesHi := Cat(tap(l.io.owner(3).index).pad(8), tap(l.io.owner(2).index).pad(8))
            backendSlotStateHi := slotPairState(2)
        } else {
            backendSlot2Tag := 0.U; backendSlot3Tag := 0.U
            backendSlotIndicesHi := 0.U; backendSlotStateHi := 0.U
        }
        backendReturnSlot := tap(l.owners.io.deq.bits)
        backendFifoCount := tap(q.io.count)
        backendStoreCause := tap(stores.io.requestStallCause)
        val adapter = board.platform.core.observationTranslation.get
        val responses = board.platform.core.observationResponses.get
        val profile = BoardSocConfig.timingParams(timingProfile, issueWidth)
        require(profile.registeredMemoryAddress && profile.earlyRecoveryIssueBlock &&
            profile.registeredTranslationHeads && profile.registeredTranslatedResponses &&
            profile.registeredStoreResponseOwners && issueWidth == 2)
        val incomingQueue = adapter.virtualRequests.get
        val checkedQueue = adapter.checked.get
        def requestMeta(r: soc.core.ooo.DataRequest): UInt = Cat(tap(r.uncached), tap(r.virtualized),
            tap(r.mask), tap(r.size), tap(r.atomicOp), tap(r.atomic), tap(r.write)).pad(64)
        def requestAuthorization(r: soc.core.ooo.DataRequest): UInt = Cat(tap(r.prefetchNextAllowed),
            tap(r.translationEpoch), tap(r.precheckedLoad), tap(r.uncached), tap(r.virtualized),
            tap(r.mask), tap(r.size), tap(r.atomicOp), tap(r.atomic), tap(r.write)).pad(64)
        cpuFlowEvents := VecInit(Seq(
            tap(incomingQueue.io.enq.valid) && tap(incomingQueue.io.enq.ready),
            tap(adapter.physicalIngressPass), tap(adapter.precheckedPass),
            tap(checkedQueue.enq.valid) && tap(checkedQueue.enq.ready), tap(adapter.identityPass),
            tap(incomingQueue.io.deq.valid) && tap(incomingQueue.io.deq.ready),
            tap(checkedQueue.enq.ready), tap(adapter.io.virtual.request.valid))).asUInt
        cpuFlowIngressAuth := requestAuthorization(adapter.io.virtual.request.bits)
        cpuFlowCheckedAuth := requestAuthorization(checkedQueue.enq.bits.request)
        cpuFlowCheckedAddress := tap(checkedQueue.enq.bits.request.address)
        cpuFlowCheckedData := tap(checkedQueue.enq.bits.request.data)
        cpuFlowCheckedHeadAuth := requestAuthorization(checkedQueue.deq.bits.request)
        cpuFlowPhysicalAuth := requestAuthorization(adapter.io.physical.request.bits)
        dataPathRequest0Address := tap(q.io.enq.bits.address)
        dataPathRequest0Data := tap(q.io.enq.bits.data)
        dataPathRequest0Meta := requestMeta(q.io.enq.bits)
        dataPathRequest1Address := tap(q.io.deq.bits.address)
        dataPathRequest1Data := tap(q.io.deq.bits.data)
        dataPathRequest1Meta := requestMeta(q.io.deq.bits)
        dataPathRequest2Address := tap(stores.io.fastStore.bits.address)
        dataPathRequest2Data := tap(stores.io.fastStore.bits.data)
        dataPathRequest2Meta := requestMeta(stores.io.fastStore.bits)
        dataPathRequest3Address := tap(stores.io.memory.request.bits.address)
        dataPathRequest3Data := tap(stores.io.memory.request.bits.data)
        dataPathRequest3Meta := requestMeta(stores.io.memory.request.bits)
        dataPathRequest4Address := tap(adapter.io.virtual.request.bits.address)
        dataPathRequest4Data := tap(adapter.io.virtual.request.bits.data)
        dataPathRequest4Meta := requestMeta(adapter.io.virtual.request.bits)
        dataPathRequest5Address := tap(adapter.incoming.bits.address)
        dataPathRequest5Data := tap(adapter.incoming.bits.data)
        dataPathRequest5Meta := requestMeta(adapter.incoming.bits)
        dataPathRequest6Address := tap(adapter.translated.io.enq.bits.request.address)
        dataPathRequest6Data := tap(adapter.translated.io.enq.bits.request.data)
        dataPathRequest6Meta := requestMeta(adapter.translated.io.enq.bits.request)
        dataPathRequest7Address := tap(adapter.translated.io.deq.bits.request.address)
        dataPathRequest7Data := tap(adapter.translated.io.deq.bits.request.data)
        dataPathRequest7Meta := requestMeta(adapter.translated.io.deq.bits.request)
        dataPathRequest8Address := tap(checkedQueue.deq.bits.request.address)
        dataPathRequest8Data := tap(checkedQueue.deq.bits.request.data)
        dataPathRequest8Meta := requestMeta(checkedQueue.deq.bits.request)
        dataPathRequest9Address := tap(adapter.io.physical.request.bits.address)
        dataPathRequest9Data := tap(adapter.io.physical.request.bits.data)
        dataPathRequest9Meta := requestMeta(adapter.io.physical.request.bits)
        dataPathReply0Data := tap(adapter.io.physical.response.bits.data)
        dataPathReply0Flags := Cat(tap(adapter.io.physical.response.bits.pageFault), tap(adapter.io.physical.response.bits.error)).pad(64)
        dataPathReply1Data := tap(adapter.io.virtual.response.bits.data)
        dataPathReply1Flags := Cat(tap(adapter.io.virtual.response.bits.pageFault), tap(adapter.io.virtual.response.bits.error)).pad(64)
        dataPathReply2Data := tap(responses.io.upstream.response.bits.data)
        dataPathReply2Flags := Cat(tap(responses.io.upstream.response.bits.pageFault), tap(responses.io.upstream.response.bits.error)).pad(64)
        dataPathReply3Data := tap(stores.io.memory.response.bits.data)
        dataPathReply3Flags := Cat(tap(stores.io.memory.response.bits.pageFault), tap(stores.io.memory.response.bits.error)).pad(64)
        dataPathReply4Data := tap(stores.io.upstream.response.bits.data)
        dataPathReply4Flags := Cat(tap(stores.io.upstream.response.bits.pageFault), tap(stores.io.upstream.response.bits.error)).pad(64)
        dataPathCounts := Cat(0.U(28.W), tap(responses.responses.count).pad(4),
            tap(adapter.owners.io.count).pad(4), tap(checkedQueue.count).pad(4),
            tap(adapter.translated.io.count).pad(4), tap(incomingQueue.io.count).pad(4),
            tap(stores.reads).pad(4), tap(stores.owners.io.count).pad(4),
            tap(stores.issued).pad(4), tap(stores.count).pad(4))
        // Exact selected-profile duplicate of reserveMemory with only issueAvailable removed.
        // The registered-address profile captures operands before this predicate. The equality
        // is checked by the host on every nonreset sample, including cycles outside the ROI.
        val reserveWithoutCapacity = !tap(b.interruptDrain) && !tap(b.reserveSystem) &&
            !tap(b.olderSystem) && !tap(b.fpMemoryEpoch) && !tap(b.contextMemoryEpoch) &&
            tap(b.memoryChoice.valid) &&
            tap(b.io.commitEnable) && !tap(b.ledger.io.recovering) &&
            (!tap(b.memoryEntry.request.atomic) || !tap(b.io.memoryBusy)) &&
            (tap(b.memoryChoice.index) === h || (tap(b.speculative) && !tap(b.blockedByStore)))
        val launchWithoutCapacity = reserveWithoutCapacity && !tap(b.earlyRecoveryIssueBlock) &&
            !tap(b.ledger.io.pendingException.valid)
        val younger = tap(b.memoryChoice.index) =/= h && !tap(b.memoryEntry.request.store) &&
            !tap(b.memoryEntry.request.atomic)
        val capacityCandidate = launchWithoutCapacity && younger && tap(l.noOtherSerial) &&
            (tap(l.io.parallel) || tap(l.othersIdle))
        dataPathEvents := VecInit(Seq(
            tap(stores.io.memory.request.valid) && tap(stores.io.memory.request.ready),
            tap(stores.io.memory.response.valid) && tap(stores.io.memory.response.ready),
            tap(stores.drainRequest), tap(stores.flowBufferedWrite), tap(stores.flowFastWrite),
            tap(stores.owners.io.deq.valid), tap(stores.owners.io.deq.bits),
            tap(stores.enqueue), tap(stores.io.forwarded), tap(stores.fastEnqueue),
            tap(b.fpMemoryEpoch) && tap(b.io.memory.request.valid) && tap(b.io.memory.request.ready),
            tap(b.fpMemoryEpoch) && tap(b.io.memory.response.valid) && tap(b.io.memory.response.ready),
            tap(adapter.io.virtual.request.valid) && tap(adapter.io.virtual.request.ready),
            tap(adapter.incoming.valid) && tap(adapter.incoming.ready),
            tap(adapter.io.translation.request.valid) && tap(adapter.io.translation.request.ready),
            tap(adapter.io.translation.response.valid) && tap(adapter.io.translation.response.ready),
            tap(adapter.translated.io.enq.valid) && tap(adapter.translated.io.enq.ready),
            tap(adapter.translated.io.deq.valid) && tap(adapter.translated.io.deq.ready),
            tap(checkedQueue.deq.valid) && tap(checkedQueue.deq.ready),
            tap(adapter.io.physical.request.valid) && tap(adapter.io.physical.request.ready),
            tap(adapter.io.virtual.response.valid) && tap(adapter.io.virtual.response.ready),
            tap(adapter.io.physical.response.valid) && tap(adapter.io.physical.response.ready),
            tap(responses.responses.enq.valid) && tap(responses.responses.enq.ready),
            tap(responses.responses.deq.valid) && tap(responses.responses.deq.ready),
            tap(adapter.waiting), tap(adapter.incoming.bits.virtualized), tap(adapter.physicalFault),
            tap(adapter.owners.io.deq.bits.fault), tap(stores.ackValid),
            tap(adapter.fault), tap(adapter.translated.io.deq.bits.pageFault), tap(adapter.physicalPageFault),
            capacityCandidate, capacityCandidate && !tap(l.available),
            tap(l.io.start.valid) && tap(l.io.start.ready) && younger,
            ((reserveWithoutCapacity && tap(l.io.issueAvailable)) === tap(b.reserveMemory)) &&
                ((launchWithoutCapacity && tap(l.io.issueAvailable)) === tap(l.io.start.valid)),
            tap(b.ordinaryRam), tap(b.memoryEntry.request.store), tap(b.memoryEntry.request.atomic), younger,
            tap(b.fpMemoryEpoch), tap(adapter.translated.io.enq.bits.pageFault),
            tap(adapter.translated.io.enq.bits.accessFault)
        )).asUInt
        backendEvents := VecInit(Seq(
            saved || (memoryReady1 && (!(store || atomic) || memoryReady2)),
            atHead(b.memoryCandidates.map(c => tap(c.valid))), choiceHead,
            tap(l.io.start.valid) && tap(l.io.start.ready),
            tap(b.directStoreFire), tap(l.available), tap(l.noOtherSerial), tap(l.othersIdle),
            tap(l.io.parallel), tap(l.io.issueAvailable), tap(l.io.start.ready),
            tap(b.memoryChoice.valid), tap(b.interruptDrain), tap(b.reserveSystem), tap(b.olderSystem),
            tap(b.fpMemoryEpoch), tap(b.io.commitEnable), tap(b.ledger.io.recovering),
            atomic && tap(b.io.memoryBusy), tap(l.io.start.valid),
            tap(q.io.enq.valid), tap(q.io.enq.ready), tap(q.io.deq.valid), tap(q.io.deq.ready),
            tap(l.io.memory.response.valid), tap(l.io.memory.response.ready),
            tap(l.io.complete.valid), tap(l.io.complete.ready), tap(l.owners.io.deq.valid),
            atHead((0 until b.p.robEntries).map(i => tap(b.eligible(i)))), tap(b.headRequest.system), tap(b.headRequest.mulDiv), store, atomic, saved,
            tap(l.io.fastLoadRetire), tap(l.io.forwarded), tap(stores.buffered), tap(stores.forward),
            tap(stores.local), tap(stores.ackValid), tap(l.io.requestOwner.valid),
            tap(l.io.start.bits.forward.valid), tap(stores.io.fastStore.valid) && tap(stores.io.fastStore.ready)
        )).asUInt
    } else {
        backendSlot2Tag := 0.U; backendSlot3Tag := 0.U
        backendSlotIndicesHi := 0.U; backendSlotStateHi := 0.U
        cpuFlowEvents := 0.U; cpuFlowIngressAuth := 0.U; cpuFlowCheckedAuth := 0.U
        cpuFlowCheckedAddress := 0.U; cpuFlowCheckedData := 0.U
        cpuFlowCheckedHeadAuth := 0.U; cpuFlowPhysicalAuth := 0.U
        dataPathReply4Data := 0.U; dataPathReply4Flags := 0.U
        dataPathEvents := 0.U; dataPathCounts := 0.U
        dataPathRequest0Address := 0.U
        dataPathRequest0Data := 0.U
        dataPathRequest0Meta := 0.U
        dataPathRequest1Address := 0.U
        dataPathRequest1Data := 0.U
        dataPathRequest1Meta := 0.U
        dataPathRequest2Address := 0.U
        dataPathRequest2Data := 0.U
        dataPathRequest2Meta := 0.U
        dataPathRequest3Address := 0.U
        dataPathRequest3Data := 0.U
        dataPathRequest3Meta := 0.U
        dataPathRequest4Address := 0.U
        dataPathRequest4Data := 0.U
        dataPathRequest4Meta := 0.U
        dataPathRequest5Address := 0.U
        dataPathRequest5Data := 0.U
        dataPathRequest5Meta := 0.U
        dataPathRequest6Address := 0.U
        dataPathRequest6Data := 0.U
        dataPathRequest6Meta := 0.U
        dataPathRequest7Address := 0.U
        dataPathRequest7Data := 0.U
        dataPathRequest7Meta := 0.U
        dataPathRequest8Address := 0.U
        dataPathRequest8Data := 0.U
        dataPathRequest8Meta := 0.U
        dataPathRequest9Address := 0.U
        dataPathRequest9Data := 0.U
        dataPathRequest9Meta := 0.U
        dataPathReply0Data := 0.U
        dataPathReply0Flags := 0.U
        dataPathReply1Data := 0.U
        dataPathReply1Flags := 0.U
        dataPathReply2Data := 0.U
        dataPathReply2Flags := 0.U
        dataPathReply3Data := 0.U
        dataPathReply3Flags := 0.U
        backendEvents := 0.U
        backendHeadTag := 0.U; backendHeadIndex := 0.U; backendQueueHeadTag := 0.U; backendQueueHeadIndex := 0.U
        backendRequestTag := 0.U; backendRequestIndex := 0.U
        backendStartTag := 0.U; backendStartIndex := 0.U
        backendCompleteTag := 0.U; backendCompleteIndex := 0.U
        backendSlot0Tag := 0.U; backendSlot1Tag := 0.U
        backendSlotIndices := 0.U; backendSlotState := 0.U; backendReturnSlot := 0.U
        backendFifoCount := 0.U; backendStoreCause := 0.U
    }

    // Test-only passive taps: no production IO or functional logic changes.
    val perfEvents = IO(Output(UInt(48.W)))
    val perfOccupancy = IO(Output(UInt(3.W)))
    val perfSupply = IO(Output(UInt(2.W)))
    val perfCapture = IO(Output(UInt(2.W)))
    val perfRename = IO(Output(UInt(2.W)))
    val perfDiscard = IO(Output(UInt(3.W)))
    val perfTranslationPhase = IO(Output(UInt(3.W)))
    val perfFetchGetSize = IO(Output(UInt(3.W)))
    val perfFetchGetAddress = IO(Output(UInt(64.W)))
    val perfCacheEvents = IO(Output(UInt(16.W)))
    val perfCacheState = IO(Output(UInt(3.W)))
    val perfCacheGetSource = IO(Output(UInt(8.W)))
    if (frontendProbes) {
        require(issueWidth == 2, "frontend probes currently describe two-wide production configuration")
        perfFetchGetSize := BoringUtils.bore(board.platform.io.activity.get.fetchGetSize)
        perfFetchGetAddress := BoringUtils.bore(board.platform.io.activity.get.fetchGetAddress)
        val cache = board.platform.instructionLineCache.get
        def cacheTap[T <: Data](signal: T): T = BoringUtils.bore(signal)
        val cacheAValid = cacheTap(cache.io.tl.a.valid)
        val cacheAReady = cacheTap(cache.io.tl.a.ready)
        perfCacheState := cacheTap(cache.perfState)
        perfCacheGetSource := cacheTap(cache.io.tl.a.bits.source)
        perfCacheEvents := VecInit(Seq(
            cacheTap(cache.perfAcceptedHit), cacheTap(cache.perfAcceptedMiss),
            cacheTap(cache.perfAcceptedFallback), cacheTap(cache.perfDemandRefillRequest),
            cacheTap(cache.perfDemandRefillComplete), cacheTap(cache.perfDemandRefillError),
            cacheTap(cache.perfDemandRefillInstall), cacheTap(cache.perfWaitingRefill),
            cacheTap(cache.perfFallbackActive), cacheTap(cache.perfRetryFallback),
            cacheTap(cache.perfWaitingPrefetch),
            cacheTap(cache.io.fetch.response.valid) && cacheTap(cache.io.fetch.response.ready),
            cacheTap(cache.io.fetch.request.valid) && cacheTap(cache.io.fetch.request.ready),
            cacheAValid && cacheAReady,
            cacheTap(cache.io.tl.d.valid) && cacheTap(cache.io.tl.d.ready),
            cacheAValid && !cacheAReady
        )).asUInt
        val c = board.platform.core.core.core
        val packet = c.fetchPacket.get
        val ledger = c.backend.ledger
        def tap[T <: Data](signal: T): T = BoringUtils.bore(signal)
        val occupancy = tap(packet.io.occupancy)
        val supply = VecInit(packet.io.supply.map(x => tap(x.valid)))
        val captured = VecInit(packet.io.captured.map(tap(_)))
        val consumed = VecInit(packet.io.consume.map(tap(_)))
        val allocate = VecInit(ledger.io.allocate.map(x => tap(x.valid)))
        val renamed = VecInit(ledger.io.renamed.map(x => tap(x.valid)))
        val pause = tap(packet.io.pause)
        val correction = tap(packet.wrongPath)
        val flush = tap(packet.io.flush.valid)
        val recovery = tap(ledger.recoveryCycle)
        val dispatch = tap(ledger.io.dispatchReady)
        val exhausted = tap(ledger.io.tagExhausted)
        val robFull = tap(ledger.io.occupancy) === ledger.p.robEntries.U
        val capacity0 = tap(ledger.faultCandidates.get.io.capacity)(0)
        val capacity1 = tap(ledger.faultCandidates.get.io.capacity)(1)
        val adapter = board.platform.fetchAdapter.get
        val virtualReq = tap(adapter.io.virtual.request.valid)
        val virtualReady = tap(adapter.io.virtual.request.ready)
        val virtualReply = tap(adapter.io.virtual.response.valid)
        val physicalReq = tap(adapter.io.physical.request.valid)
        val physicalReady = tap(adapter.io.physical.request.ready)
        val physicalReply = tap(adapter.io.physical.response.valid)
        val physicalWait = tap(adapter.io.physical.response.ready)
        val translate = tap(adapter.io.translation.response.ready)
        val translationReq = tap(adapter.io.translation.request.valid)
        val translationReady = tap(adapter.io.translation.request.ready)
        val translationReply = tap(adapter.io.translation.response.valid)
        val f = board.platform.frontend
        val supplyCount = PopCount(supply)
        val consumeCount = PopCount(consumed)
        perfOccupancy := occupancy
        perfSupply := supplyCount
        perfCapture := PopCount(captured)
        perfRename := PopCount(renamed)
        perfDiscard := Mux(correction || flush, occupancy - consumeCount, 0.U)
        // Exclusive observed adapter phases; phase 5 means no exposed predicate matched.
        perfTranslationPhase := Mux(virtualReply, 4.U, Mux(virtualReady, 0.U, Mux(translate, 1.U,
            Mux(physicalReq, 2.U, Mux(physicalWait, 3.U, 5.U)))))
        val events = Seq(
            pause, correction, flush, recovery, tap(ledger.io.recovering),
            allocate(0) && !dispatch, allocate(0) && recovery,
            allocate(0) && exhausted, allocate(0) && robFull,
            allocate(0) && !capacity0,
            allocate(1) && renamed(0) && !capacity1,
            occupancy === 4.U && consumeCount > 0.U && supply(0) && !pause && !correction && !flush,
            occupancy === 3.U && consumeCount > 0.U && supplyCount === 2.U && !pause && !correction && !flush,
            supply(0) && !captured(0), supply(0) && !supply(1),
            virtualReq && virtualReady, virtualReq && !virtualReady, virtualReply,
            physicalReq && physicalReady, physicalReq && !physicalReady,
            physicalReply && physicalWait,
            translationReq && translationReady, translationReply && translate,
            translationReq && translationReady && tap(adapter.io.translation.request.bits.mode) === 0.U,
            tap(f.io.pause), tap(f.io.invalidate), !tap(f.io.instruction0.valid),
            tap(c.backend.headTrapAccepted), tap(c.backend.headSystemAccepted),
            tap(c.backend.ordinaryLocalRedirectAccepted) && tap(c.backend.localInclusive),
            tap(c.backend.ordinaryLocalRedirectAccepted) && !tap(c.backend.localInclusive),
            tap(c.backend.externalWins) && tap(ledger.io.recoveryAccepted),
            tap(board.platform.io.activity.get.fetchGetFire),
            allocate(0), renamed(0), tap(ledger.io.freeCount) === 0.U,
            tap(f.io.enable), translate && !translationReply,
            physicalWait && !physicalReply,
            !supply(0) && occupancy === 0.U && !pause && !correction && !flush,
            virtualReply && virtualReq && !virtualReady,
            virtualReq && virtualReady && (tap(adapter.io.vmState.satp)(63, 60) === 0.U ||
                tap(adapter.io.privilege) === 3.U)
        )
        perfEvents := VecInit(events).asUInt
    } else {
        perfEvents := 0.U
        perfOccupancy := 0.U
        perfSupply := 0.U
        perfCapture := 0.U
        perfRename := 0.U
        perfDiscard := 0.U
        perfTranslationPhase := 0.U
        perfFetchGetSize := 0.U
        perfFetchGetAddress := 0.U
        perfCacheEvents := 0.U
        perfCacheState := 0.U
        perfCacheGetSource := 0.U
    }
}

/** Same memory sizes, address map, latency and compact core as the FPGA board. */
