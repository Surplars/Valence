package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.platform.CommonA1RebuildProfile

/** Passive scalar observations of existing production state, never test authority. */
class MulLoadRowObservation(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val source1 = UInt(p.physBits.W)
    val source2 = UInt(p.physBits.W)
    val destination = UInt(p.physBits.W)
    val writesRd = Bool()
    val pending = Bool()
    val memoryLive = Bool()
    val killed = Bool()
    val ownerReady1 = Bool()
    val ownerReady2 = Bool()
    val memory = Bool()
    val store = Bool()
    val atomic = Bool()
    val mulDiv = Bool()
    val operation = UInt(3.W)
    val word = Bool()
}
class MulLoadReservationObservation(p: OooParams) extends Bundle {
    val live = Bool()
    val owner = new RobToken(p)
    val cancel = Bool()
}
class MulLoadSlotObservation(p: OooParams) extends Bundle {
    val live = Bool()
    val owner = new RobToken(p)
    val phase = UInt(2.W)
    val cancel = Bool()
    val completeValid = Bool()
    val completeReady = Bool()
    val result = new BackendCompletion(p)
    val startValid = Bool()
    val startReady = Bool()
    val startOwner = new RobToken(p)
}
class MulLoadPhysicalWrite(p: OooParams) extends Bundle {
    val address = UInt(p.physBits.W)
    val data = UInt(64.W)
}

/** Real fourth-profile backend plus its production decode, DTA, response buffer and
  * translation service. External ports supply native RAM/PTE responses only.
  * No selector/authority reimplementation, forced state, or test-mode credit exists.
  * This is a backend integration fixture, not a full fetch/cache/CPU model.
  */
class MulLoadOperandCaptureBackendGsim(enabled: Boolean) extends Module {
    val profile = if (enabled) CommonA1RebuildProfile.FullR1M3MulLoadOperandCaptureExperiment
        else CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4
    val config = profile.config
    val p = config.coreParams
    val control = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4.config.coreParams
    require(p == control.copy(registeredMulLoadOperandCapture = enabled))
    require(!p.contextOwnedInstructionPrefetch && !p.loadPayloadNomination)
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 && p.memoryEntries == 4)
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)
    require(p.dataReturnHandleBits == 0 && p.postedProofConfig.isEmpty)
    require(p.registeredMulDivOperands && p.sharedMulDivOperandReads && !p.registeredLoadResultReady)
    val io = IO(new Bundle {
        val instruction0 = Input(Valid(UInt(32.W)))
        val instruction1 = Input(Valid(UInt(32.W)))
        val pc0 = Input(UInt(64.W))
        val pc1 = Input(UInt(64.W))
        val commitEnable = Input(Bool())
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val renamed0 = Output(Valid(new RenamedInstruction(p)))
        val renamed1 = Output(Valid(new RenamedInstruction(p)))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val issued0 = Output(Valid(new BackendCompletion(p)))
        val issued1 = Output(Valid(new BackendCompletion(p)))
        val redirect = Output(Valid(new FrontendRedirect(p)))
        val trap = Output(Valid(new HeadException(p)))
        val headException = Output(Valid(new HeadException(p)))
        val recovery = Output(Valid(new RecoveryRequest(p)))
        val recoveryAccepted = Output(Bool())
        val ledgerRecoveryAccepted = Output(Bool())
        val recovering = Output(Bool())
        val head = Output(UInt(p.robBits.W))
        val occupancy = Output(UInt(p.countBits.W))
        val idle = Output(Bool())
        val physical = new DataPort(p.dataReturnHandleBits)
        val pte = new SvPteReadPort
        val vm = Output(new VmCsrState)
        val upstreamRequest = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
        val upstreamRequestReady = Output(Bool())
        val upstreamResponse = Output(Valid(new DataResponse(p.dataReturnHandleBits)))
        val upstreamResponseReady = Output(Bool())
        val mulStart = Output(Valid(new MultiplyDivideRequest(p)))
        val mulReady = Output(Bool())
        val mulCaptured = Output(new MultiplyDivideRequest(p))
        val mulArithmeticFire = Output(Bool())
        val mulComplete = Output(Valid(new BackendCompletion(p)))
        val mulCompleteReady = Output(Bool())
        val mulCount = Output(UInt(4.W))
        val mulPop = Output(Bool())
        val mulHead = Output(UInt(3.W))
        val mulTail = Output(UInt(3.W))
        val divStart = Output(Valid(new MultiplyDivideRequest(p)))
        val divReady = Output(Bool())
        val divBusy = Output(Bool())
        val divCancel = Output(Bool())
        val divOwner = Output(new RobToken(p))
        val divComplete = Output(Valid(new BackendCompletion(p)))
        val divCompleteReady = Output(Bool())
        val lsuStart = Output(Valid(new MemoryOperation(p)))
        val lsuReady = Output(Bool())
        val lsuRequestOwner = Output(Valid(new RobToken(p)))
        val lsuRequestFire = Output(Bool())
        val lsuStartSlot = Output(UInt(2.W))
        val lsuCompleteSlot = Output(UInt(2.W))
        val lsuComplete = Output(Valid(new BackendCompletion(p)))
        val lsuCompleteReady = Output(Bool())
        val loadWake = Output(Valid(UInt(p.physBits.W)))
        val selectedValid = Output(Bool())
        val selectedIndex = Output(UInt(p.robBits.W))
        val mulGrant = Output(Bool())
        val divGrant = Output(Bool())
        val reserveMulDiv = Output(Bool())
        val mStart = Output(Bool())
        val lateAllowed = Output(Bool())
        val readyMask = Output(UInt(p.physicalRegs.W))
        val pendingMask = Output(UInt(p.robEntries.W))
        val memoryLiveMask = Output(UInt(p.robEntries.W))
        val killedMask = Output(UInt(p.robEntries.W))
        val reserve0 = Output(Valid(UInt(p.physBits.W)))
        val reserve1 = Output(Valid(UInt(p.physBits.W)))
        val write0 = Output(Valid(new MulLoadPhysicalWrite(p)))
        val write1 = Output(Valid(new MulLoadPhysicalWrite(p)))
        val dispatch0 = Output(Valid(UInt(p.robBits.W)))
        val dispatch1 = Output(Valid(UInt(p.robBits.W)))
        val aluCapture0 = Output(Bool())
        val aluCapture1 = Output(Bool())
        val row0 = Output(new MulLoadRowObservation(p))
        val row1 = Output(new MulLoadRowObservation(p))
        val row2 = Output(new MulLoadRowObservation(p))
        val row3 = Output(new MulLoadRowObservation(p))
        val row4 = Output(new MulLoadRowObservation(p))
        val row5 = Output(new MulLoadRowObservation(p))
        val row6 = Output(new MulLoadRowObservation(p))
        val row7 = Output(new MulLoadRowObservation(p))
        val row8 = Output(new MulLoadRowObservation(p))
        val row9 = Output(new MulLoadRowObservation(p))
        val row10 = Output(new MulLoadRowObservation(p))
        val row11 = Output(new MulLoadRowObservation(p))
        val row12 = Output(new MulLoadRowObservation(p))
        val row13 = Output(new MulLoadRowObservation(p))
        val row14 = Output(new MulLoadRowObservation(p))
        val row15 = Output(new MulLoadRowObservation(p))
        val mulSlot0 = Output(new MulLoadReservationObservation(p))
        val mulSlot1 = Output(new MulLoadReservationObservation(p))
        val mulSlot2 = Output(new MulLoadReservationObservation(p))
        val mulSlot3 = Output(new MulLoadReservationObservation(p))
        val mulSlot4 = Output(new MulLoadReservationObservation(p))
        val mulSlot5 = Output(new MulLoadReservationObservation(p))
        val mulSlot6 = Output(new MulLoadReservationObservation(p))
        val mulSlot7 = Output(new MulLoadReservationObservation(p))
        val loadSlot0 = Output(new MulLoadSlotObservation(p))
        val loadSlot1 = Output(new MulLoadSlotObservation(p))
        val loadSlot2 = Output(new MulLoadSlotObservation(p))
        val loadSlot3 = Output(new MulLoadSlotObservation(p))
    })
    // Match CommonA1CpuTile -> MappedMachineCore -> IntegerCore constructor lineage.
    // Their extra experimental backend constructor flags remain the default false.
    val backend = Module(new IntegerBackend(p,
        canonicalHandoff = config.cache.independentDemandAdmission && p.canonicalVirtualStoreOverlap,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
        retirementSlotIdentity = p.retirementSlotIdentity))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = config.translationHitFlow, usePublishedPmpChanges = p.pmpChangePublicationEnabled,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent, queuedHeadSelection = p.queuedHeadSelection,
        alignedNextLinePmp = p.alignedNextLinePmp, factorCheckedNextAllowed = p.factorCheckedNextAllowed,
        certifiedLoadIngress = p.certifiedLoadIngress))
    val responses = Module(new DataResponseBuffer(registerPayload = p.registeredTranslatedResponses,
        registerHead = p.registeredTranslationHeads, emptyFlow = p.translatedResponseEmptyFlow,
        returnConfig = p.cpuReturnConfig))
    val translation = Module(new SvTranslationService(p.virtualMemoryLevels, config.dataTranslationEntries,
        p.pmpEntries, loadPeek = true, writeReadReuse = config.dataTlbWriteReadReuse,
        decodedNaturalPmp = p.decodedNaturalPmp))
    val requests = Seq.tabulate(2) { lane =>
        val decoder = Module(new IntegerDecode(p.machineSystem, p.atomicMemory, p.parallelDecodeLegality,
            p.parallelBitLegality, p.fpEnabled, p.fpConfig))
        val in = Seq(io.instruction0, io.instruction1)(lane)
        decoder.io.instruction := in.bits
        decoder.io.pc := Seq(io.pc0, io.pc1)(lane)
        val request = Wire(Valid(new IntegerRequest))
        request.valid := in.valid
        request.bits := decoder.io.decoded
        backend.io.allocate(lane) := request
        request
    }
    backend.io.rawDestinations.foreach(_ := VecInit(requests.map(_.bits.rename.rd)))
    backend.io.rawRequests.foreach(_ := VecInit(requests.map(_.bits.rename)))
    backend.io.fetchFaultMask.foreach(_ := 0.U)
    backend.io.commitEnable := io.commitEnable
    // Registered production branches/traps supply recovery internally. No forced owner input.
    backend.io.recover := 0.U.asTypeOf(backend.io.recover)
    backend.io.inspectRegister := io.inspectRegister
    backend.io.imsic.get.request.ready := true.B
    backend.io.imsic.get.response.valid := false.B
    backend.io.imsic.get.response.bits := 0.U.asTypeOf(backend.io.imsic.get.response.bits)
    backend.io.externalInterrupt.get := false.B
    backend.io.supervisorExternalInterrupt.get := false.B
    backend.io.timerInterrupt.get := false.B
    backend.io.timeValue.get := 0.U
    backend.io.emptyPc.get := io.pc0
    backend.io.fetchQuiescent.get := true.B
    backend.io.fenceIFlushReady.get := true.B
    backend.io.externalPrefetchBusy.foreach(_ := false.B)
    val flushReady = adapter.io.idle && translation.io.idle
    val flush = backend.io.vmFlush.get && flushReady
    backend.io.vmFlushReady.get := flushReady
    translation.io.flush := flush
    adapter.io.precheckFlush.get := flush
    adapter.io.vmState := backend.io.vmState.get
    adapter.io.pmpState := backend.io.pmpState.get
    adapter.io.pmpRawChanged.foreach(_ := backend.io.pmpRawChanged.get)
    translation.io.pmpState := backend.io.pmpState.get
    responses.io.upstream <> backend.io.memory
    adapter.io.virtual <> responses.io.downstream
    translation.io.client <> adapter.io.translation
    backend.io.loadPrecheck.get <> adapter.io.loadPrecheck.get
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    adapter.io.canonicalStoreOrigin.get := backend.io.canonicalStore.get.requestOrigin
    adapter.io.frozenStoreProof.foreach(_ := backend.io.canonicalStore.get.requestFrozenProof.get)
    backend.io.canonicalStore.get.checked := adapter.io.canonicalStoreCertificate.get
    io.physical <> adapter.io.physical
    io.pte <> translation.io.memory
    io.vm := backend.io.vmState.get
    io.renamed0 := backend.io.renamed(0)
    io.renamed1 := backend.io.renamed(1)
    io.commit0 := backend.io.commit(0)
    io.commit1 := backend.io.commit(1)
    io.issued0 := backend.io.issued(0)
    io.issued1 := backend.io.issued(1)
    io.redirect := backend.io.redirect
    io.trap := backend.io.trap.get
    io.headException := backend.io.headException
    io.recovering := backend.io.recovering
    io.recoveryAccepted := backend.io.recoveryAccepted
    io.occupancy := backend.io.occupancy
    io.committedValue := backend.io.committedValue
    io.upstreamRequest.valid := backend.io.memory.request.valid
    io.upstreamRequest.bits := backend.io.memory.request.bits
    io.upstreamRequestReady := backend.io.memory.request.ready
    io.upstreamResponse.valid := backend.io.memory.response.valid
    io.upstreamResponse.bits := backend.io.memory.response.bits
    io.upstreamResponseReady := backend.io.memory.response.ready
    io.idle := backend.io.ownersIdle && adapter.io.idle && translation.io.idle && responses.io.idle
    def tap[T <: Data](value: T): T = BoringUtils.bore(value)
    io.recovery := tap(backend.ledger.io.recover)
    io.ledgerRecoveryAccepted := tap(backend.ledger.io.recoveryAccepted)
    io.head := tap(backend.head)
    io.mulStart.valid := tap(backend.multiplier.io.start.valid)
    io.mulStart.bits := tap(backend.multiplier.io.start.bits)
    io.mulReady := tap(backend.multiplier.io.start.ready)
    io.mulCaptured := tap(backend.multiplier.operands)
    io.mulArithmeticFire := tap(backend.multiplier.arithmeticFire)
    io.mulComplete.valid := tap(backend.multiplier.io.complete.valid)
    io.mulComplete.bits := tap(backend.multiplier.io.complete.bits)
    io.mulCompleteReady := tap(backend.multiplier.io.complete.ready)
    io.mulCount := tap(backend.multiplier.count)
    io.mulPop := tap(backend.multiplier.pop)
    io.mulHead := tap(backend.multiplier.head)
    io.mulTail := tap(backend.multiplier.tail)
    io.divStart.valid := tap(backend.mulDiv.io.start.valid)
    io.divStart.bits := tap(backend.mulDiv.io.start.bits)
    io.divReady := tap(backend.mulDiv.io.start.ready)
    io.divBusy := tap(backend.mulDiv.io.busy)
    io.divCancel := tap(backend.mulDiv.io.cancel)
    io.divOwner := tap(backend.mulDiv.io.owner)
    io.divComplete.valid := tap(backend.mulDiv.io.complete.valid)
    io.divComplete.bits := tap(backend.mulDiv.io.complete.bits)
    io.divCompleteReady := tap(backend.mulDiv.io.complete.ready)
    io.lsuStart.valid := tap(backend.lsu.io.start.valid)
    io.lsuStart.bits := tap(backend.lsu.io.start.bits)
    io.lsuReady := tap(backend.lsu.io.start.ready)
    io.lsuRequestOwner := tap(backend.lsu.io.requestOwner)
    io.lsuRequestFire := tap(backend.lsu.io.memory.request.valid) && tap(backend.lsu.io.memory.request.ready)
    io.lsuStartSlot := tap(backend.lsu.chosen)
    io.lsuCompleteSlot := tap(backend.lsu.completion.io.chosen)
    io.lsuComplete.valid := tap(backend.lsu.io.complete.valid)
    io.lsuComplete.bits := tap(backend.lsu.io.complete.bits)
    io.lsuCompleteReady := tap(backend.lsu.io.complete.ready)
    io.loadWake := tap(backend.loadIssueWake)
    io.selectedValid := tap(backend.mulDivChoice.valid)
    io.selectedIndex := tap(backend.mulDivChoice.index)
    io.mulGrant := tap(backend.mulDivGrants(0))
    io.divGrant := tap(backend.mulDivGrants(1))
    io.reserveMulDiv := tap(backend.reserveMulDiv)
    io.mStart := tap(backend.mStart)
    io.lateAllowed := backend.mulLoadCaptureAllowed.map(tap(_)).getOrElse(true.B)
    io.readyMask := tap(backend.ready).asUInt
    io.pendingMask := tap(backend.pending).asUInt
    io.memoryLiveMask := tap(backend.memoryLive).asUInt
    io.killedMask := tap(backend.killed).asUInt
    io.reserve0 := tap(backend.readyUpdate.get.io.reserve(0))
    io.reserve1 := tap(backend.readyUpdate.get.io.reserve(1))
    for ((out, lane) <- Seq(io.write0, io.write1).zipWithIndex) {
        val write = tap(backend.physicalWrites.get(lane))
        out.valid := write.valid
        out.bits.address := write.bits.address
        out.bits.data := write.bits.data
    }
    io.dispatch0 := tap(backend.dispatched(0))
    io.dispatch1 := tap(backend.dispatched(1))
    io.aluCapture0 := tap(backend.executionStages(0).io.enq.valid) && tap(backend.executionStages(0).io.enq.ready)
    io.aluCapture1 := tap(backend.executionStages(1).io.enq.valid) && tap(backend.executionStages(1).io.enq.ready)
    for ((out, i) <- Seq(io.row0, io.row1, io.row2, io.row3, io.row4, io.row5, io.row6, io.row7, io.row8, io.row9, io.row10, io.row11, io.row12, io.row13, io.row14, io.row15).zipWithIndex) {
        val entry = tap(backend.issueEntries(i))
        out.token := entry.renamed.token
        out.source1 := entry.renamed.source1
        out.source2 := entry.renamed.source2
        out.destination := entry.renamed.destination
        out.writesRd := entry.renamed.writesRd
        out.pending := tap(backend.pending(i))
        out.memoryLive := tap(backend.memoryLive(i))
        out.killed := tap(backend.killed(i))
        out.ownerReady1 := tap(backend.ownerReady.get.io.ready1(i))
        out.ownerReady2 := tap(backend.ownerReady.get.io.ready2(i))
        out.memory := entry.request.memory
        out.store := entry.request.store
        out.atomic := entry.request.atomic
        out.mulDiv := entry.request.mulDiv
        out.operation := entry.request.mulDivOp
        out.word := entry.request.word
    }
    for ((out, i) <- Seq(io.mulSlot0, io.mulSlot1, io.mulSlot2, io.mulSlot3, io.mulSlot4, io.mulSlot5, io.mulSlot6, io.mulSlot7).zipWithIndex) {
        out.live := tap(backend.multiplier.io.live(i))
        out.owner := tap(backend.multiplier.io.owner(i))
        out.cancel := tap(backend.multiplier.io.cancel(i))
    }
    for ((out, i) <- Seq(io.loadSlot0, io.loadSlot1, io.loadSlot2, io.loadSlot3).zipWithIndex) {
        val slot = backend.lsu.slots(i)
        out.live := tap(backend.lsu.io.live(i))
        out.owner := tap(backend.lsu.io.owner(i))
        out.phase := tap(slot.io.phase)
        out.cancel := tap(slot.io.cancel)
        out.completeValid := tap(slot.io.complete.valid)
        out.completeReady := tap(slot.io.complete.ready)
        out.result := tap(slot.io.complete.bits)
        out.startValid := tap(slot.io.start.valid)
        out.startReady := tap(slot.io.start.ready)
        out.startOwner := tap(slot.io.start.bits.token)
    }
}
