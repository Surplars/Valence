package soc.platform

import chisel3._
import chisel3.util._
import soc.core.ooo._
import soc.bus.tilelink._

/** CPU-domain extraction of the public Selected A1 profile. All private frontend,
  * MMU/PMP, register/retirement state and L1s remain here. No ROM, timer, APLIC,
  * DMA, Home or DDR manager is instantiated in this tile. The first common
  * profile explicitly adds the existing whole-line return capability only.
  * Optional runtime parking drains architectural/execution/private owners before
  * the shared fabric epoch; default static profiles retain no runtime endpoint.
  */
class CommonA1CpuTile(
    config: FpgaNextConfig = FpgaNextConfig.Selected.copy(internalLineGrant = true),
    boundary: CommonCpuTilePortParams = CommonCpuTilePortParams(),
    memoryProfile: Option[CommonA1MemoryProfile] = None,
    sideEffectFreeFetchRanges: Seq[SideEffectFreeFetchRange] = Seq.empty
) extends Module {
    // Validate the actual final configuration. A profile is not a second set
    // of overrides: contradictory config/profile inputs must fail elaboration.
    memoryProfile.foreach(_.validate(config, boundary))
    require(!config.fetchThirdPacketLookahead ||
        (memoryProfile.contains(CommonA1MemoryProfile.ExperimentalIdentityFetchHorizon) ||
            memoryProfile.contains(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor) ||
            memoryProfile.contains(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor2) ||
            memoryProfile.contains(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor3) ||
            memoryProfile.contains(CommonA1MemoryProfile.ExperimentalEfficiencyRefactor4)),
        "identity fetch horizon requires its explicit final-configuration policy")
    require(!config.fetchThirdPacketLookahead || sideEffectFreeFetchRanges.nonEmpty,
        "identity fetch horizon requires explicitly supplied physical RAM ranges from the connected fabric")
    require(!config.fetchThirdPacketLookahead || sideEffectFreeFetchRanges.forall(range =>
        range.base >= CommonPlatformAbi.ramBase && range.endExclusive <= config.ramEndExclusive),
        "Common A1 safe fetch ranges must stay within its physical RAM aperture, excluding ROM and MMIO")
    require(!boundary.runtimeMaintenance || boundary.runtimeCancellation,
        "A1 runtime parking requires acknowledged release")
    private val p = config.coreParams
    private val cacheConfig = config.cache
    require(config.issueWidth == 2 && config.isaProfile == "rv64gc")
    require(config.instructionCacheLines == 512 && config.dataCacheLines == 512 && config.cacheWays == 2)
    require(cacheConfig.readMshrs == 2 && cacheConfig.responseEntries == 2 && cacheConfig.writebackEntries == 2)
    require(config.internalLineGrant && boundary.coherent.sinkBits == cacheConfig.sinkBits)
    require(p.dataReturnHandleBits == 0 && p.postedProofConfig.isEmpty,
        "common A1 native transport requires ordered replies, not tagged/posted CPU candidates")
    private val staged = BoardSocConfig.usesStagedMemoryFabric(config.timingProfile, p)
    require(staged, "common A1 extraction keeps the checked registered physical boundary")
    val io = IO(new Bundle {
        val bus = new CommonCpuTilePort(boundary)
        val runtimeHeld = if (boundary.runtimeMaintenance) Some(Valid(UInt(boundary.maintenanceEpochBits.W))) else None
        val hold = Input(Bool())
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val commit = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val trap = Output(Valid(new HeadException(p)))
        val fetchPc = Output(UInt(64.W))
        val memoryBusy = Output(Bool())
        val tlbHit = Output(Vec(2, Bool()))
        val pteRead = Output(Vec(2, Bool()))
    })
    val core = Module(new MappedMachineCore(p, dataTranslation = true, stagedMemoryFabric = true,
        bufferTranslatedResponses = true, translationHitFlow = config.translationHitFlow,
        canonicalHandoff = cacheConfig.independentDemandAdmission && p.canonicalVirtualStoreOverlap,
        externalInterruptFabric = true, runtimeQuiesce = boundary.runtimeMaintenance))
    val park = if (boundary.runtimeMaintenance) Some(Module(new CommonA1RuntimePark(boundary))) else None
    core.io.quiesce.foreach(_ := park.get.io.stopAdmission)
    val compactFetchKeys = p.frontendCacheSets == 16 && p.renameWidth == 2 && p.pmpEntries == 16 &&
        p.compressedInstructions && p.stableFetchFaultMetadata && p.alignedFetchPmp && p.rawFetchPresence &&
        p.parallelFetchTagLookup && p.parallelFetchAlignment && p.registeredFetchWindow &&
        p.independentFetchPayloadCapture && p.fetchPreviousPacket && p.alignedFetchPermissionStage &&
        p.fetchAddressBeforePmp
    require(!config.fetchThirdPacketLookahead || (p.fetchThirdPacketLookahead && config.fetchTransactionSlots == 2 &&
        p.renameWidth == 2 && p.compressedInstructions && p.registeredFetchWindow && p.alignedFetchPmp &&
        p.alignedFetchSinglePage && p.registeredTranslationHeads && p.fetchReplyTurnover &&
        p.fetchIdentityTranslation && !p.fetchAddressBeforePmp && !p.alignedFetchPermissionStage &&
        !p.fetchPreviousPacket && !compactFetchKeys),
        "identity fetch horizon must use the actual strict two-owner aligned frontend and two-result adapter")
    val frontend = Module(new SynchronousFetch(16, p.compressedInstructions, p.frontendCacheSets,
        p.renameWidth, stableFaultMetadata = p.stableFetchFaultMetadata, alignedFetchPmp = p.alignedFetchPmp,
        rawFetchPresence = p.rawFetchPresence, parallelFetchTagLookup = p.parallelFetchTagLookup,
        parallelAlignment = p.parallelFetchAlignment, registeredWindow = p.registeredFetchWindow,
        independentPayloadCapture = p.independentFetchPayloadCapture, fetchPreviousPacket = p.fetchPreviousPacket,
        boundedRequestFrontier = p.alignedFetchPermissionStage, fetchAddressBeforePmp = p.fetchAddressBeforePmp,
        compactCacheKeys = compactFetchKeys, transactionSlots = config.fetchTransactionSlots,
        fetchThirdPacketLookahead = config.fetchThirdPacketLookahead,
        sideEffectFreeFetchRanges = sideEffectFreeFetchRanges, canonicalFetchCacheKeys = config.canonicalFetchCacheKeys))
    val fetchAdapter = Module(new InstructionTranslationAdapter(p, transactionSlots = config.fetchTransactionSlots,
        withRequestContext = true))
    // transactionSlots == 2 selects PipelinedAlignedInstructionTranslation and its fixed two-slot
    // FetchCompletionLedger; the third query does not add an accepted owner or a result slot.
    require(!config.fetchThirdPacketLookahead ||
        (frontend.transactionSlots == 2 && fetchAdapter.transactionSlots == 2),
        "identity fetch horizon cannot change accepted-owner or result capacity")
    require(frontend.transactionSlots == fetchAdapter.transactionSlots,
        "Common A1 frontend and translation ownership capacities must agree")
    fetchAdapter.io.virtual <> frontend.io.memory
    fetchAdapter.io.vmState := core.io.vmState.get
    fetchAdapter.io.privilege := core.io.fetchPrivilege.get
    fetchAdapter.io.pmpState := core.io.pmpState.get
    if (p.fetchAddressBeforePmp) when(frontend.io.memory.request.valid) {
        assert(fetchAdapter.io.virtual.request.ready, "prepared fetch lost its direct translation owner")
    }
    val physicalFetch = if (p.bufferedFetchRequests) {
        val requests = Module(new InstructionRequestBuffer(fetchAdapter.io.physical.packetWords,
            p.flowThroughFetchRequests, p.independentFetchCapture, withRequestContext = true))
        requests.io.upstream <> fetchAdapter.io.physical
        requests.io.downstream
    } else fetchAdapter.io.physical
    val fetchCache = Module(new InstructionLineCache(boundary.instruction,
        ramBase = config.ramBase, ramBytes = config.ddrBytes, romBytes = CommonPlatformAbi.romBytes,
        lines = config.instructionCacheLines, packetWords = 2,
        prefetchEnabled = false, // public two-word frontend already owns its fetch window
        bankedData = config.bankedInstructionData,
        parallelFallbackAddresses = p.parallelFetchAddresses, tagConfig = config.tags, withRequestContext = true))
    require(physicalFetch.withRequestContext && fetchCache.io.fetch.withRequestContext,
        "Common A1 physical fetch must retain its owner permission context")
    fetchCache.io.fetch <> physicalFetch
    fetchCache.io.pmpState := core.io.pmpState.get
    fetchCache.io.privilege := core.io.fetchPrivilege.get
    fetchCache.io.invalidate := core.io.invalidateFetch
    io.bus.instructionFetch <> fetchCache.io.tl

    val selection = Module(new CommonPrivateMemoryRouter(config.ramBase, config.ddrBytes))
    selection.io.cpu <> core.io.memory
    val cache = CoherentLineCacheModule.build(base = config.ramBase, bytes = config.ddrBytes,
        lines = config.dataCacheLines, params = boundary.coherent, ways = config.cacheWays,
        concurrency = cacheConfig, tagConfig = config.tags,
        registerProbeLookup = config.registerProbeLookup, localReadSelection = config.localCacheReadSelection,
        allowSharedFutureLruWriteData = p.sharedMemoryAddressState && cacheConfig.futureHomeWayReservation &&
            cacheConfig.storePrefetchLruVictim)
    cache.io.upstream <> selection.io.cache
    io.bus.coherent(1) <> cache.io.tl
    cache.io.lineGrant.get <> io.bus.lineGrant(1)
    io.bus.coherent(0).a.valid := false.B
    io.bus.coherent(0).a.bits := 0.U.asTypeOf(io.bus.coherent(0).a.bits)
    io.bus.coherent(0).b.ready := false.B
    io.bus.coherent(0).c.valid := false.B
    io.bus.coherent(0).c.bits := 0.U.asTypeOf(io.bus.coherent(0).c.bits)
    io.bus.coherent(0).d.ready := false.B
    io.bus.coherent(0).e.valid := false.B
    io.bus.coherent(0).e.bits := 0.U.asTypeOf(io.bus.coherent(0).e.bits)
    io.bus.lineGrant(0).ready := false.B
    assert(!io.bus.coherent(0).b.valid && !io.bus.coherent(0).d.valid && !io.bus.lineGrant(0).valid,
        "fabric addressed an inactive A1 coherent I-client")
    if (p.dataNextLinePrefetch) {
        core.io.externalPrefetchBusy.get := cache.io.prefetchBusy
        when(cache.io.upstream.request.fire && cache.io.upstream.request.bits.prefetchNextAllowed) {
            assert(core.io.memoryBusy, "A1 prefetch lost the original CPU memory owner")
        }
    }

    val walkers = (0 until 2).map(i => Module(new SvTranslationService(3,
        entries = if (i == 1) config.dataTranslationEntries else 8,
        loadPeek = p.virtualRamLoadPrecheck && i == 1,
        writeReadReuse = config.dataTlbWriteReadReuse && i == 1, decodedNaturalPmp = p.decodedNaturalPmp)))
    val pte = Seq.fill(2)(Module(new SvPteDataBridge(4)))
    val walkArbiter = Module(new SharedDataArbiter)
    val memoryArbiter = Module(new SharedDataArbiter(registerResponseOwners = true))
    val walkIdle = VecInit((0 until 2).map(i => walkers(i).io.idle && pte(i).io.idle)).asUInt.andR
    val flush = core.io.vmFlush.get && walkIdle
    for (i <- 0 until 2) {
        walkers(i).io.flush := flush
        walkers(i).io.pmpState := core.io.pmpState.get
        pte(i).io.flush := flush
        pte(i).io.walk <> walkers(i).io.memory
        walkArbiter.io.clients(i) <> pte(i).io.data
        io.tlbHit(i) := walkers(i).io.tlbHit
        io.pteRead(i) := pte(i).io.physicalRead
    }
    walkers(0).io.client <> fetchAdapter.io.translation
    walkers(1).io.client <> core.io.translation.get
    if (p.virtualRamLoadPrecheck) {
        walkers(1).io.loadPeek.get <> core.io.translationPeek.get
        core.io.precheckFlush.get := flush
    }
    core.io.vmFlushReady.get := walkIdle
    memoryArbiter.io.clients(0) <> cache.io.downstream
    memoryArbiter.io.clients(1) <> walkArbiter.io.memory
    val requests = Module(new DataRequestBuffer(registerHead = p.registeredFabricBoundary))
    requests.io.upstream <> memoryArbiter.io.memory
    requests.io.requestCpu := memoryArbiter.io.memoryRequestClient0
    val direct = Module(new CommonNativeOwnerAdapter(boundary, carriesClear = false))
    val physical = Module(new CommonNativeOwnerAdapter(boundary, carriesClear = true))
    direct.io.native <> selection.io.uncached
    direct.io.needsCoherenceLookup := true.B
    direct.io.clearReservation := false.B
    physical.io.native <> requests.io.downstream
    physical.io.needsCoherenceLookup := !requests.io.downstreamRequestCpu
    physical.io.clearReservation := core.io.trap.valid
    io.bus.scalar(0) <> direct.io.transport
    io.bus.scalar(1) <> physical.io.transport

    // Existing two-phase FENCE.I ordering: private dirty writeback first,
    // then shared Home/DDR plus transport ownership, then fetch invalidation.
    val epoch = RegInit(0.U(boundary.maintenanceEpochBits.W))
    val fenceSeen = RegInit(false.B)
    val requestSent = RegInit(false.B)
    val fabricDone = RegInit(false.B)
    when(core.io.fenceIFlush && !fenceSeen) { epoch := epoch + 1.U; fenceSeen := true.B }
    when(!core.io.fenceIFlush) { fenceSeen := false.B; requestSent := false.B; fabricDone := false.B }
    cache.io.flushRequest := core.io.fenceIFlush || park.map(_.io.flush).getOrElse(false.B)
    val fetchIdle = frontend.io.quiescent && fetchAdapter.io.idle && fetchCache.io.idle
    val privateIdle = selection.io.idle && direct.io.idle && physical.io.idle && requests.io.idle && walkIdle
    io.bus.maintenanceStatus.valid := core.io.fenceIFlush && fenceSeen && cache.io.flushDone &&
        privateIdle && fetchIdle && !requestSent
    io.bus.maintenanceStatus.bits.epoch := epoch
    io.bus.maintenanceStatus.bits.privateOwnersDrained := privateIdle
    io.bus.maintenanceStatus.bits.dirtyWritebackCompleted := cache.io.flushDone
    io.bus.maintenanceStatus.bits.fetchQuiescent := fetchIdle
    io.bus.maintenanceStatus.bits.invalidationsCompleted := false.B
    when(io.bus.maintenanceStatus.fire && core.io.fenceIFlush) { requestSent := true.B }
    io.bus.fabricDrainedEpoch.ready := requestSent && !fabricDone
    when(io.bus.fabricDrainedEpoch.fire && core.io.fenceIFlush) {
        assert(io.bus.fabricDrainedEpoch.bits === epoch, "A1 accepted a stale fabric drain epoch")
        fabricDone := true.B
    }
    core.io.fenceIFlushReady := cache.io.flushDone && fabricDone
    io.bus.maintenanceStatus.bits.holdUntilResume.foreach(_ := false.B)
    if (boundary.runtimeMaintenance) {
        val owner = park.get
        owner.io.command <> io.bus.maintenance
        owner.io.fenceBusy := core.io.fenceIFlush || fenceSeen
        owner.io.architecturalIdle := core.io.ownersIdle.get && fetchIdle && privateIdle && !core.io.trap.valid
        owner.io.privateIdle := privateIdle && fetchIdle && cache.io.quiescent
        owner.io.flushDone := cache.io.flushDone
        owner.io.status.ready := false.B
        owner.io.fabricDone.valid := false.B
        owner.io.fabricDone.bits := io.bus.fabricDrainedEpoch.bits
        when(owner.io.stopped) {
            io.bus.maintenanceStatus <> owner.io.status
            owner.io.fabricDone <> io.bus.fabricDrainedEpoch
        }
        owner.io.resume <> io.bus.maintenanceResume.get
        io.bus.maintenanceResumed.get <> owner.io.resumed
        io.runtimeHeld.get := owner.io.held
        when(owner.io.stopped) {
            assert(!core.io.commit.map(_.valid).reduce(_ || _) && !core.io.trap.valid,
                "A1 parked epoch performed architectural work")
        }
        when(owner.io.held.valid) {
            assert(core.io.ownersIdle.get && !core.io.memoryBusy && privateIdle && fetchIdle && cache.io.quiescent,
                "A1 held epoch must retain every LSU, translation, response, cache and native owner drain")
        }
    } else io.bus.maintenance.ready := false.B

    frontend.io.pc := core.io.fetchPc
    if (p.alignedFetchPermissionStage) {
        frontend.io.requestFrontier.get := core.io.fetchRequestFrontier.get
        frontend.io.suppressRequest.get := core.io.suppressFetchRequest.get
        core.io.instructionFaultOffsets.get := frontend.io.instructionFaultOffsets
    }
    frontend.io.enable := !io.hold
    frontend.io.invalidate := core.io.invalidateFetch
    frontend.io.pause := core.io.pauseFetch.get || park.map(_.io.stopAdmission).getOrElse(false.B)
    frontend.io.pmpState := core.io.pmpState.get
    frontend.io.privilege := core.io.fetchPrivilege.get
    frontend.io.virtualized := core.io.vmState.get.satp(63, 60) =/= 0.U && core.io.fetchPrivilege.get =/= 3.U
    core.io.fetchQuiescent.get := fetchIdle
    core.io.instructions := frontend.io.instructions
    core.io.instructionFaults := frontend.io.instructionFaults
    core.io.instructionPageFaults := frontend.io.instructionPageFaults
    core.io.instructionFaultAddresses.foreach(_ := frontend.io.instructionFaultAddresses)
    core.io.commitEnable := !io.hold && !park.map(_.io.stopped).getOrElse(false.B)
    core.io.sources := 0.U
    core.io.externalMsi.get <> io.bus.msi
    core.io.timerInterrupt := io.bus.timerInterrupt
    core.io.timeValue := io.bus.timeSnapshot
    // ABI 1 exposes no MSIP array; neither tile may invent an extra MMIO device.
    assert(!io.bus.softwareInterrupt, "A1 ABI 1 has no machine software interrupt source")
    core.io.inspectRegister := io.inspectRegister
    io.commit := core.io.commit
    io.trap := core.io.trap
    io.fetchPc := core.io.fetchPc
    io.committedValue := core.io.committedValue
    io.memoryBusy := core.io.memoryBusy
}
