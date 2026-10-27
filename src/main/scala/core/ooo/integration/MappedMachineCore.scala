package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.interrupt.{AplicParams, ImsicParams}
import soc.platform.CommonInterruptFabric

/** Software-configured APLIC on the CPU data address space. See docs/core-mmio.md. */
class MappedMachineCore(
    p: OooParams = OooParams(),
    imsicParams: ImsicParams = ImsicParams(),
    aplicParams: AplicParams = AplicParams(),
    dataTranslation: Boolean = false,
    stagedMemoryFabric: Boolean = false,
    bufferTranslatedResponses: Boolean = false,
    translationHitFlow: Boolean = false,
    canonicalHandoff: Boolean = false
,
    preselectRedirectTokenMatches: Boolean = false,
    proofBankControlDecoupling: Boolean = false, val projectedRequestHead: Boolean = false, val factorPreparedStorePool: Boolean = false, val registerNextLineDecision: Boolean = false, val registeredMemoryPreparationDescriptor: Boolean = false, val backendNaturalAlignedPmp: Boolean = false, val earlyLoadPreparationDescriptor: Boolean = false, val virtualStoreOperandLookahead: Boolean = false, val bankedStoreData: Boolean = false,
    externalInterruptFabric: Boolean = false, runtimeQuiesce: Boolean = false) extends Module {
    require(aplicParams.msiBase == imsicParams.machineBase && aplicParams.identities == imsicParams.identities)
    require(!dataTranslation || p.virtualMemoryLevels > 0)
    // The ordinary final-port shortcut relies on both real upstream producer chains:
    // integer LSU -> RegisteredRequestQueue -> StoreBuffer, and FP live PMP ->
    // LoadStoreUnit(registerStart=true). It cannot be inferred from an arbitrary
    // standalone DataPort or enabled without the existing checked/return stages.
    require(!p.loadPayloadNomination || (p.coexistingPhysicalLoadIngress && p.certifiedLoadIngress),
        "load payload nomination preserves both existing final-port ingress owners")
    require(!p.coexistingPhysicalLoadIngress || (p.certifiedLoadIngress && p.bufferedRamStores &&
        p.registeredMemoryRequests && dataTranslation && stagedMemoryFabric && bufferTranslatedResponses),
        "coexisting physical ingress preserves registered producers and the existing checked/return boundaries")
    require(!p.certifiedLoadIngress || (dataTranslation && stagedMemoryFabric &&
        bufferTranslatedResponses && translationHitFlow),
        "certified load ingress requires the actual checked adapter and retained response boundary")
    require(!p.queuedHeadSelection || (dataTranslation && stagedMemoryFabric &&
        (p.precheckedDataRequestFlow || translationHitFlow)),
        "queued head selection requires a real checked translation-flow source")
    require(!p.alignedNextLinePmp || dataTranslation,
        "aligned next-line PMP requires the actual data adapter")
    require(!translationHitFlow || (dataTranslation && stagedMemoryFabric),
        "translation hit flow requires the staged data MMU")
    require(!p.virtualRamLoadPrecheck || (dataTranslation && stagedMemoryFabric),
        "virtual load precheck requires the staged physical authorization adapter")
    require(!p.canonicalVirtualStoreOverlap || (dataTranslation && stagedMemoryFabric),
        "canonical virtual stores require the registered checked authorization boundary")
    require(!p.postedStoreMerge || (dataTranslation && stagedMemoryFabric),
        "posted stores require checked authorization before the common APLIC/memory routing boundary")
    require(!stagedMemoryFabric || dataTranslation)
    require(!bufferTranslatedResponses || (dataTranslation && stagedMemoryFabric))
    require(!p.registeredTranslatedResponses || bufferTranslatedResponses)
    require(!p.directMemoryResponse || stagedMemoryFabric)
    val io = IO(new Bundle {
        val quiesce = if (runtimeQuiesce) Some(Input(Bool())) else None
        val ownersIdle = if (runtimeQuiesce) Some(Output(Bool())) else None
        val timerInterrupt  = Input(Bool())
        val timeValue       = Input(UInt(64.W))
        val instructions    = Input(Vec(p.renameWidth, Valid(UInt(32.W))))
        val instructionFaults = Input(Vec(p.renameWidth, Bool()))
        val instructionPageFaults = Input(Vec(p.renameWidth, Bool()))
        val instructionFaultAddresses = if (p.compressedInstructions)
            Some(Input(Vec(p.renameWidth, UInt(64.W)))) else None
        val accepted        = Output(Vec(p.renameWidth, Bool()))
        val fetchPc         = Output(UInt(64.W))
        val fetchRequestFrontier = if (p.alignedFetchPermissionStage) Some(Output(UInt(64.W))) else None
        val suppressFetchRequest = if (p.alignedFetchPermissionStage) Some(Output(Bool())) else None
        val instructionFaultOffsets = if (p.alignedFetchPermissionStage)
            Some(Input(Vec(p.renameWidth, UInt(5.W)))) else None
        val pmpState        = if (p.pmpEntries > 0) Some(Output(new PmpState)) else None
        val fetchPrivilege  = if (p.pmpEntries > 0) Some(Output(UInt(2.W))) else None
        val fetchQuiescent  = if (p.pmpEntries > 0) Some(Input(Bool())) else None
        val pauseFetch      = if (p.pmpEntries > 0) Some(Output(Bool())) else None
        val vmState         = if (p.virtualMemoryLevels > 0) Some(Output(new VmCsrState)) else None
        val vmFlush         = if (p.virtualMemoryLevels > 0) Some(Output(Bool())) else None
        val vmFlushReady    = if (p.virtualMemoryLevels > 0) Some(Input(Bool())) else None
        val translation     = if (dataTranslation) Some(new SvTranslationPort) else None
        val translationPeek = if (p.virtualRamLoadPrecheck) Some(new SvTranslationPeekPort) else None
        val precheckFlush = if (p.virtualRamLoadPrecheck) Some(Input(Bool())) else None
        val commitEnable    = Input(Bool())
        val commit          = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val trap            = Output(Valid(new HeadException(p)))
        val redirect        = Output(Valid(new FrontendRedirect(p)))
        val invalidateFetch = Output(Bool())
        val fenceIFlush     = Output(Bool())
        val fenceIFlushReady = Input(Bool())
        val recovering      = Output(Bool())
        val memory          = new DataPort(p.dataReturnHandleBits)
        val posted = p.postedProofConfig.map(c => Flipped(new PostedStoreCachePort(c)))
        val sources         = Input(UInt(aplicParams.sources.W))
        val externalMsi = if (externalInterruptFabric) Some(Flipped(new soc.ip.bus.RegisterPort)) else None
        val msiError        = Output(Bool())
        val externalPending = Output(UInt(imsicParams.files.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue  = Output(UInt(64.W))
        val robOccupancy    = Output(UInt(p.countBits.W))
        val headProfile     = Output(new HeadProfile)
        val issueCount      = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val externalPrefetchBusy = if (p.dataNextLinePrefetch) Some(Input(Bool())) else None
        val memoryBusy      = Output(Bool())
    })
    require(
        p.speculativeRamBytes == 0 ||
            p.speculativeRamBase + p.speculativeRamBytes <= aplicParams.base ||
            aplicParams.base + 32768 <= p.speculativeRamBase,
        "APLIC domains must not overlap speculative or buffered RAM"
    )
    require(!p.taggedStoreReturns || (stagedMemoryFabric && dataTranslation && bufferTranslatedResponses),
        "tagged CPU returns require checked translation and both registered response credits")
    val core  = Module(new MachineCore(p, imsicParams, canonicalHandoff,
        preselectRedirectTokenMatches = preselectRedirectTokenMatches,
        proofBankControlDecoupling = proofBankControlDecoupling,
        projectedRequestHead = projectedRequestHead, factorPreparedStorePool = factorPreparedStorePool,
        registeredMemoryPreparationDescriptor = registeredMemoryPreparationDescriptor, backendNaturalAlignedPmp = backendNaturalAlignedPmp,
        earlyLoadPreparationDescriptor = earlyLoadPreparationDescriptor,
        virtualStoreOperandLookahead = virtualStoreOperandLookahead,
        bankedStoreData = bankedStoreData, runtimeQuiesce = runtimeQuiesce))
    val interrupts = if (!externalInterruptFabric) Some(Module(new CommonInterruptFabric(aplicParams, imsicParams))) else None
    val supervisorParams = aplicParams.copy(base = aplicParams.base + 16384,
        msiBase = imsicParams.supervisorBase)
    core.io.msi <> io.externalMsi.getOrElse(interrupts.get.io.msi)
    val router = if (!externalInterruptFabric && !stagedMemoryFabric) Some(Module(new CoreRegisterRouter(aplicParams.base))) else None
    val supervisorRouter = if (!externalInterruptFabric && !stagedMemoryFabric)
        Some(Module(new CoreRegisterRouter(supervisorParams.base))) else None
    val parallelRouter = if (!externalInterruptFabric && stagedMemoryFabric) Some(Module(new ParallelRegisterRouter(Seq(
        (aplicParams.base, BigInt(16384)), (supervisorParams.base, BigInt(16384))
    ), bypassMemoryShift = p.directMemoryResponse, returnConfig = p.cpuReturnConfig))) else None
    val mappedUpstream = if (externalInterruptFabric) io.memory
        else parallelRouter.map(_.io.upstream).getOrElse(router.get.io.upstream)
    // Elaboration-only references for passive board-wrapper lineage observation.
    var observationTranslation: Option[DataTranslationAdapter] = None
    var observationResponses: Option[DataResponseBuffer] = None
    if (dataTranslation) {
        val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = stagedMemoryFabric,
            translationHitFlow = translationHitFlow, usePublishedPmpChanges = p.pmpChangePublicationEnabled,
            registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
            queuedHeadSelection = p.queuedHeadSelection, alignedNextLinePmp = p.alignedNextLinePmp,
            factorCheckedNextAllowed = p.factorCheckedNextAllowed,
            registerNextLineDecision = registerNextLineDecision, certifiedLoadIngress = p.certifiedLoadIngress))
        observationTranslation = Some(adapter)
        if (bufferTranslatedResponses) {
            // The platform's existing two response credits are relocated here,
            // ahead of APLIC/fault returns as well as external memory returns.
            val responses = Module(new DataResponseBuffer(registerPayload = p.registeredTranslatedResponses,
                registerHead = p.registeredTranslationHeads, emptyFlow = p.translatedResponseEmptyFlow,
                returnConfig = p.cpuReturnConfig))
            observationResponses = Some(responses)
            responses.io.upstream <> core.io.memory
            adapter.io.virtual <> responses.io.downstream
        } else adapter.io.virtual <> core.io.memory
        adapter.io.physical <> mappedUpstream
        adapter.io.translation <> io.translation.get
        if (p.virtualRamLoadPrecheck) {
            adapter.io.loadPrecheck.get <> core.io.loadPrecheck.get
            adapter.io.translationPeek.get <> io.translationPeek.get
            adapter.io.precheckFlush.get := io.precheckFlush.get
        }
        if (p.canonicalVirtualStoreOverlap) {
            // The optional response buffer stores responses only: these requests share one fire.
            adapter.io.canonicalStoreOrigin.get := core.io.canonicalStore.get.requestOrigin
            adapter.io.frozenStoreProof.foreach(_ := core.io.canonicalStore.get.requestFrozenProof.get)
            core.io.canonicalStore.get.checked := adapter.io.canonicalStoreCertificate.get
            when(core.io.memory.request.fire) { assert(adapter.io.virtual.request.fire) }
        }
        adapter.io.vmState := core.io.vmState.get
        adapter.io.pmpState := core.io.pmpState.get
        adapter.io.pmpRawChanged.foreach(_ := core.io.pmpRawChanged.get)
        io.posted.foreach { posted =>
            val transport = adapter.io.posted.get
            // DataResponseBuffer and both routing fabrics contain response-only
            // storage: request payload and proof share the exact same handshake.
            transport.upstreamProof := core.io.posted.get.requestProof
            transport.externalBusy := posted.busy
            core.io.posted.get.externalBusy := posted.busy
            core.io.posted.get.contextEpoch := transport.contextEpoch
            core.io.posted.get.blockNew := transport.contextChanging
            val drained = !core.io.memoryBusy && adapter.io.idle && !core.io.posted.get.busy
            transport.aggregateDrained := drained && !core.io.posted.get.starting &&
                !core.io.posted.get.requestProof.valid
            posted.contextEpoch := transport.contextEpoch
            posted.requestProof := transport.requestProof
            posted.requestProof.valid := io.memory.request.valid && transport.requestProof.valid
            posted.seal := core.io.posted.get.seal || transport.contextChanging || core.io.recovering
            // episodeActive is deliberately absent: it describes identity, not work.
            posted.endEpisode := transport.aggregateDrained && !transport.requestProof.valid &&
                !posted.requestProof.valid
            when(posted.endEpisode) {
                assert(!posted.busy && !core.io.posted.get.starting && !io.memory.request.fire)
            }
            when(io.memory.request.fire && posted.requestProof.valid) {
                assert(adapter.io.physical.request.fire,
                    "the request-only router must transport the saved checked proof on the same edge")
            }
            PostedStoreCpu.held(io.memory.request, posted.requestProof)
        }
    } else {
        mappedUpstream <> core.io.memory
    }
    if (!externalInterruptFabric) parallelRouter match {
        case Some(fabric) =>
            fabric.io.registers(0) <> interrupts.get.io.machineRegisters
            fabric.io.registers(1) <> interrupts.get.io.supervisorRegisters
            io.memory <> fabric.io.memory
        case None =>
            router.get.io.registers <> interrupts.get.io.machineRegisters
            supervisorRouter.get.io.upstream <> router.get.io.memory
            supervisorRouter.get.io.registers <> interrupts.get.io.supervisorRegisters
            io.memory <> supervisorRouter.get.io.memory
    }
    interrupts.foreach(_.io.sources := io.sources)
    io.msiError := interrupts.map(_.io.msiError).getOrElse(false.B)
    core.io.timerInterrupt  := io.timerInterrupt
    core.io.timeValue       := io.timeValue
    io.fenceIFlush := core.io.fenceIFlush
    core.io.fenceIFlushReady := io.fenceIFlushReady
    core.io.instructions    := io.instructions
    core.io.instructionFaults := io.instructionFaults
    core.io.instructionPageFaults := io.instructionPageFaults
    core.io.instructionFaultAddresses.foreach(_ := io.instructionFaultAddresses.get)
    if (p.alignedFetchPermissionStage) {
        core.io.instructionFaultOffsets.get := io.instructionFaultOffsets.get
        io.fetchRequestFrontier.get := core.io.fetchRequestFrontier.get
        io.suppressFetchRequest.get := core.io.suppressFetchRequest.get
    }
    if (p.pmpEntries > 0) {
        io.pmpState.get := core.io.pmpState.get
        io.fetchPrivilege.get := core.io.fetchPrivilege.get
        core.io.fetchQuiescent.get := io.fetchQuiescent.get
        io.pauseFetch.get := core.io.pauseFetch.get
    }
    if (p.virtualMemoryLevels > 0) {
        io.vmState.get := core.io.vmState.get
        io.vmFlush.get := core.io.vmFlush.get
        core.io.vmFlushReady.get := io.vmFlushReady.get
    }
    io.quiesce.foreach(q => core.io.quiesce.get := q)
    io.ownersIdle.foreach(_ := core.io.ownersIdle.get &&
        observationTranslation.map(_.io.idle).getOrElse(true.B) &&
        observationResponses.map(_.io.idle).getOrElse(true.B))
    core.io.commitEnable    := io.commitEnable
    core.io.inspectRegister := io.inspectRegister
    io.accepted             := core.io.accepted
    io.fetchPc              := core.io.fetchPc
    io.commit               := core.io.commit
    io.trap                 := core.io.trap
    io.redirect             := core.io.redirect
    io.invalidateFetch      := core.io.invalidateFetch
    io.recovering           := core.io.recovering
    io.externalPending      := core.io.externalPending
    io.committedValue       := core.io.committedValue
    io.robOccupancy         := core.io.robOccupancy
    io.headProfile          := core.io.headProfile
    io.issueCount           := core.io.issueCount
    if (p.dataNextLinePrefetch) core.io.externalPrefetchBusy.get := io.externalPrefetchBusy.get
    io.memoryBusy           := core.io.memoryBusy
}
