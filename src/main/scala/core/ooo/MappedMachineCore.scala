package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.interrupt.{Aplic, AplicParams, ImsicParams}
import soc.ip.bus.TwoMasterRegisterArbiter

/** Software-configured APLIC on the CPU data address space. See docs/core-mmio.md. */
class MappedMachineCore(
    p: OooParams = OooParams(),
    imsicParams: ImsicParams = ImsicParams(),
    aplicParams: AplicParams = AplicParams(),
    dataTranslation: Boolean = false,
    stagedMemoryFabric: Boolean = false,
    bufferTranslatedResponses: Boolean = false
) extends Module {
    require(aplicParams.msiBase == imsicParams.machineBase && aplicParams.identities == imsicParams.identities)
    require(!dataTranslation || p.virtualMemoryLevels > 0)
    require(!p.virtualRamLoadPrecheck || (dataTranslation && stagedMemoryFabric),
        "virtual load precheck requires the staged physical authorization adapter")
    require(!stagedMemoryFabric || dataTranslation)
    require(!bufferTranslatedResponses || (dataTranslation && stagedMemoryFabric))
    require(!p.registeredTranslatedResponses || bufferTranslatedResponses)
    require(!p.directMemoryResponse || stagedMemoryFabric)
    val io = IO(new Bundle {
        val timerInterrupt  = Input(Bool())
        val timeValue       = Input(UInt(64.W))
        val instructions    = Input(Vec(p.renameWidth, Valid(UInt(32.W))))
        val instructionFaults = Input(Vec(p.renameWidth, Bool()))
        val instructionPageFaults = Input(Vec(p.renameWidth, Bool()))
        val instructionFaultAddresses = if (p.compressedInstructions)
            Some(Input(Vec(p.renameWidth, UInt(64.W)))) else None
        val accepted        = Output(Vec(p.renameWidth, Bool()))
        val fetchPc         = Output(UInt(64.W))
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
        val memory          = new DataPort
        val sources         = Input(UInt(aplicParams.sources.W))
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
    val core  = Module(new MachineCore(p, imsicParams))
    val aplic = Module(new Aplic(aplicParams, hasChild = true,
        childMsiBase = imsicParams.supervisorBase))
    val supervisorParams = aplicParams.copy(base = aplicParams.base + 16384,
        msiBase = imsicParams.supervisorBase)
    val supervisorAplic = Module(new Aplic(supervisorParams, hasParent = true))
    val msiArbiter = Module(new TwoMasterRegisterArbiter)
    msiArbiter.io.masters(0) <> aplic.io.msi
    msiArbiter.io.masters(1) <> supervisorAplic.io.msi
    core.io.msi <> msiArbiter.io.downstream
    val router = if (!stagedMemoryFabric) Some(Module(new CoreRegisterRouter(aplicParams.base))) else None
    val supervisorRouter = if (!stagedMemoryFabric)
        Some(Module(new CoreRegisterRouter(supervisorParams.base))) else None
    val parallelRouter = if (stagedMemoryFabric) Some(Module(new ParallelRegisterRouter(Seq(
        (aplicParams.base, BigInt(16384)), (supervisorParams.base, BigInt(16384))
    ), bypassMemoryShift = p.directMemoryResponse))) else None
    val mappedUpstream = parallelRouter.map(_.io.upstream).getOrElse(router.get.io.upstream)
    // Elaboration-only references for passive board-wrapper lineage observation.
    var observationTranslation: Option[DataTranslationAdapter] = None
    var observationResponses: Option[DataResponseBuffer] = None
    if (dataTranslation) {
        val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = stagedMemoryFabric))
        observationTranslation = Some(adapter)
        if (bufferTranslatedResponses) {
            // The platform's existing two response credits are relocated here,
            // ahead of APLIC/fault returns as well as external memory returns.
            val responses = Module(new DataResponseBuffer(registerPayload = p.registeredTranslatedResponses,
                registerHead = p.registeredTranslationHeads, emptyFlow = p.translatedResponseEmptyFlow))
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
        adapter.io.vmState := core.io.vmState.get
        adapter.io.pmpState := core.io.pmpState.get
    } else {
        mappedUpstream <> core.io.memory
    }
    parallelRouter match {
        case Some(fabric) =>
            fabric.io.registers(0) <> aplic.io.mmio
            fabric.io.registers(1) <> supervisorAplic.io.mmio
            io.memory <> fabric.io.memory
        case None =>
            router.get.io.registers <> aplic.io.mmio
            supervisorRouter.get.io.upstream <> router.get.io.memory
            supervisorRouter.get.io.registers <> supervisorAplic.io.mmio
            io.memory <> supervisorRouter.get.io.memory
    }
    aplic.io.sources        := io.sources
    supervisorAplic.io.sources := aplic.io.childSources
    supervisorAplic.io.parentEnabled.get := aplic.io.childEnabled
    io.msiError             := aplic.io.msiError || supervisorAplic.io.msiError
    core.io.timerInterrupt  := io.timerInterrupt
    core.io.timeValue       := io.timeValue
    io.fenceIFlush := core.io.fenceIFlush
    core.io.fenceIFlushReady := io.fenceIFlushReady
    core.io.instructions    := io.instructions
    core.io.instructionFaults := io.instructionFaults
    core.io.instructionPageFaults := io.instructionPageFaults
    core.io.instructionFaultAddresses.foreach(_ := io.instructionFaultAddresses.get)
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
