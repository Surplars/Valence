package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.isa.MCause

/** Decoded operation input, not an instruction decoder. Immediate is already extended to XLEN. */
class IntegerRequest extends Bundle {
    val predictedNextPc = Valid(UInt(64.W))
    val rename          = new RenameRequest
    val fetchFault      = Bool()
    val fetchPageFault  = Bool()
    val fetchTval       = UInt(64.W)
    val expandedInstruction = UInt(32.W)
    val operation       = UInt(6.W)
    val system          = Bool()
    val mulDiv          = Bool()
    val mulDivOp        = UInt(3.W)
    val word            = Bool()
    val usePc           = Bool()
    val useImmediate    = Bool()
    val immediate       = UInt(64.W)
    val controlFlow     = UInt(4.W)
    val memory          = Bool()
    val atomic          = Bool()
    val atomicOp        = UInt(5.W)
    val store           = Bool()
    val memorySize      = UInt(2.W)
    val memoryUnsigned  = Bool()
}

private[ooo] class IntegerIssueEntry(p: OooParams) extends Bundle {
    val renamed = new RenamedInstruction(p)
    val request = new IntegerRequest
}

/** Read-only scheduler and retirement-head state for cycle attribution; it does not participate in scheduling. */
class HeadProfile extends Bundle {
    val valid = Bool()
    val done = Bool()
    val pc = UInt(64.W)
    val queued = Bool()
    val operandsReady = Bool()
    val memory = Bool()
    val memoryPhase = UInt(2.W)
    val memoryCompletionBlocked = Bool()
    val storePrepared = Bool()
    val memoryStarting = Bool()
    val memorySlotAvailable = Bool()
    val memoryRequestSelected = Bool()
    val memoryRequestStallCause = UInt(3.W)
    // Read-only attribution for a ready younger RAM load selected by the memory scheduler.
    val candidateLoadPc = UInt(64.W)
    val candidateLoadBlockedByStore = Bool()
    val candidateLoadBlockedByUnknownStore = Bool()
}

/** Executing integer backend with ROB-indexed reservation slots and a physical value/ready file.
  *
  * Target: completionWidth independent ALU results/cycle and one dependent ALU per cycle after fill. No combinational
  * result-to-select feedback by default: writes become available on the next cycle. An optional registered LSU
  * completion bypass wakes dependent ALU, memory and mul/div work earlier. Selection uses balanced oldest-ready
  * tournaments. The optional registeredIssueExecute boundary separates PRF selection from ALU/writeback, keeps two
  * independent II-1 execution slots, and forwards ordinary ALU data only into the next operand registers. Otherwise
  * PRF muxes, selection, ALU and writeback form an unpipelined path; frequency/area are unverified and
  * wider configurations require a separate physical design assessment. Initial architectural registers are zero for
  * this standalone bring-up interface, not an ISA reset claim.
  */
class IntegerBackend(val p: OooParams = OooParams()) extends Module {
    require(!p.registeredIssueExecute || (p.completionWidth == 2 && p.registeredBranchRedirect &&
        p.precompleteMispredictedBranch && p.registeredRobRetirement && !p.fastBufferedStoreRetire &&
        !p.fastHeadLoadRetire && !p.moveAlias),
        "operand execution stages require the two-slot, non-aliased, registered redirect/retirement contract")
    val io = IO(new Bundle {
        val rawDestinations = if (p.parallelArchitecturalDestinations)
            Some(Input(Vec(p.renameWidth, UInt(5.W)))) else None
        val rawRequests = if (p.tentativeRenameSources)
            Some(Input(Vec(p.renameWidth, new RenameRequest))) else None
        val fetchFaultMask = if (p.tentativeRenameSources) Some(Input(UInt(p.renameWidth.W))) else None
        val imsic                       = if (p.machineSystem) Some(new MachineCsrPort) else None
        val externalInterrupt           = if (p.machineSystem) Some(Input(Bool())) else None
        val supervisorExternalInterrupt = if (p.machineSystem) Some(Input(Bool())) else None
        val timerInterrupt              = if (p.machineSystem) Some(Input(Bool())) else None
        val timeValue                   = if (p.machineSystem) Some(Input(UInt(64.W))) else None
        val emptyPc                     = if (p.machineSystem) Some(Input(UInt(64.W))) else None
        val trap                        = if (p.machineSystem) Some(Output(Valid(new HeadException(p)))) else None
        val pmpState                    = if (p.machineSystem) Some(Output(new PmpState)) else None
        val fetchPrivilege              = if (p.machineSystem) Some(Output(UInt(2.W))) else None
        val fetchQuiescent               = if (p.pmpEntries > 0) Some(Input(Bool())) else None
        val pauseFetch                   = if (p.pmpEntries > 0) Some(Output(Bool())) else None
        val vmState                      = if (p.virtualMemoryLevels > 0) Some(Output(new VmCsrState)) else None
        val vmFlush                      = if (p.virtualMemoryLevels > 0) Some(Output(Bool())) else None
        val vmFlushReady                 = if (p.virtualMemoryLevels > 0) Some(Input(Bool())) else None
        val fenceIFlush                  = if (p.machineSystem) Some(Output(Bool())) else None
        val fenceIFlushReady             = if (p.machineSystem) Some(Input(Bool())) else None
        val allocate                    = Input(Vec(p.renameWidth, Valid(new IntegerRequest)))
        val renamed                     = Output(Vec(p.renameWidth, Valid(new RenamedInstruction(p))))
        val commitEnable                = Input(Bool())
        val commit                      = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val recover                     = Input(Valid(new RecoveryRequest(p)))
        val recoveryAccepted            = Output(Bool())
        val recovering                  = Output(Bool())
        val occupancy                   = Output(UInt(p.countBits.W))
        val headProfile                 = Output(new HeadProfile)
        val issued                      = Output(Vec(p.completionWidth, Valid(new BackendCompletion(p))))
        val headException               = Output(Valid(new HeadException(p)))
        val inspectRegister             = Input(UInt(5.W))
        val committedValue              = Output(UInt(64.W))
        val redirect                    = Output(Valid(new FrontendRedirect(p)))
        val invalidateFetch             = Output(Bool())
        val memory                      = new DataPort
        val loadPrecheck = if (p.virtualRamLoadPrecheck) Some(new VirtualLoadPrecheckPort) else None
        val memoryBusy                  = Output(Bool())
        val externalPrefetchBusy = if (p.dataNextLinePrefetch) Some(Input(Bool())) else None
        val issueCount                  = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val memoryDiscarded             = Output(Bool())
        val memoryForwarded             = Output(Bool())
        // Per lane, bit 0/1 witnesses actual operand capture from a not-yet-ready load result.
        val loadIssueForwarded = if (p.registeredLoadIssueForwarding)
            Some(Output(Vec(p.completionWidth, UInt(2.W)))) else None
        val mulDivCancelled             = Output(Bool())
        val mulDivOverlap               = Output(Bool())
        val mulDivBlocked               = Output(Bool())
        val mulDivConcurrent            = Output(Bool())
        val mulDivMultiCancel           = Output(Bool())
    })
    val ledger          = Module(new RenameRob(p))
    ledger.io.rawDestinations.foreach(_ := io.rawDestinations.get)
    ledger.io.rawRequests.foreach(_ := io.rawRequests.get)
    ledger.io.fetchFaultMask.foreach(_ := io.fetchFaultMask.get)
    val lsu             = Module(new ParallelLoadStoreUnit(p))
    val mulDiv          = Module(new MultiplyDivide(p, divisionOnly = true))
    val multiplier      = Module(new PipelinedMultiply(p))
    val systemUnit      = if (p.machineSystem) Some(Module(new MachineSystemUnit(p))) else None
    val pmpState        = WireDefault(0.U.asTypeOf(new PmpState))
    val dataPrivilege   = WireDefault(3.U(2.W))
    val systemComplete  = Wire(Decoupled(new BackendCompletion(p)))
    val systemRedirect  = WireDefault(false.B)
    val systemInvalidate = WireDefault(false.B)
    val reserveSystem   = WireDefault(false.B)
    val systemStart     = WireDefault(false.B)
    val systemProtected = RegInit(false.B)
    // pending(head) clears at start, before CSR execution updates the context.
    // Retain this owner through real retirement so a younger LSU cannot capture
    // old MPRV/SATP/PMP authorization in that intervening cycle. Ordinary FP
    // arithmetic does not change memory context and retains its prior overlap.
    val systemContextBarrier = RegInit(false.B)
    val contextMemoryEpoch = systemProtected && systemContextBarrier
    val systemOwner     = RegInit(0.U.asTypeOf(new RobToken(p)))
    val systemFpMemory = if (p.fpEnabled) Some(RegInit(false.B)) else None
    val fpMemoryEpoch = systemProtected && systemFpMemory.getOrElse(false.B)
    val automaticTrap   = WireDefault(false.B)
    val headTrapRequest = WireDefault(false.B)
    ledger.io.headTrap.foreach(_.valid := headTrapRequest)
    val headTrapAccepted = ledger.io.headTrap.map(_.accepted).getOrElse(false.B)
    val headSystemRequest = WireDefault(false.B)
    ledger.io.headSystem.foreach(_.valid := headSystemRequest)
    val headSystemAccepted = ledger.io.headSystem.map(_.accepted).getOrElse(false.B)
    val earlyRecoveryIssueBlock = WireDefault(false.B)
    // A precompleted misprediction must not retire before its registered redirect is processed.
    val branchRetirementHold = WireDefault(false.B)
    val replayRetirementHold = WireDefault(false.B)
    val emptyTrap       = WireDefault(false.B)
    val interruptDrain  = WireDefault(false.B)
    val trapEvent       = WireDefault(0.U.asTypeOf(new HeadException(p)))
    val trapTarget      = WireDefault(0.U(64.W))
    val recovery        = Wire(Valid(new RecoveryRequest(p)))
    recovery             := io.recover
    systemComplete.valid := false.B
    systemComplete.bits  := 0.U.asTypeOf(new BackendCompletion(p))
    val mCompleteValid = mulDiv.io.complete.valid || multiplier.io.complete.valid
    // Irrevocable head memory ownership survives the response until retirement, including commit backpressure.
    val memoryProtected = RegInit(false.B)
    val memoryOwner     = Reg(new RobToken(p))
    val integerMemory = Wire(new DataPort)
    val integerMemoryBusy = WireDefault(lsu.io.busy)
    io.memoryBusy      := integerMemoryBusy || io.externalPrefetchBusy.getOrElse(false.B)
    io.memoryDiscarded := lsu.io.discarded
    io.memoryForwarded := lsu.io.forwarded
    val storeBufferStallCause = WireDefault(0.U(3.W))
    val fastStoreReady = WireDefault(false.B)
    val fastStoreRequest = WireDefault(0.U.asTypeOf(new DataRequest))
    val fastStoreValid = WireDefault(false.B)
    // Elaboration-only references for passive test-wrapper observation; no hardware or ports.
    var observationRequests: Option[Queue[DataRequest]] = None
    var observationStores: Option[StoreBuffer] = None
    if (p.bufferedRamStores) {
        val stores = Module(new StoreBuffer(p))
        observationStores = Some(stores)
        if (p.registeredMemoryRequests) {
            // The LSU owns the response as soon as its request enters this ordered,
            // non-flow queue. A cancelled speculative read still drains normally.
            val requests = Module(new Queue(new DataRequest, p.memoryEntries, pipe = false, flow = false))
            observationRequests = Some(requests)
            requests.io.enq <> lsu.io.memory.request
            stores.io.upstream.request <> requests.io.deq
            // Queue storage is undefined while empty. Keep only the size/shift
            // operand defined, using registered queue validity (not late issue).
            stores.io.upstream.request.bits.size := Mux(requests.io.deq.valid, requests.io.deq.bits.size, 0.U)
            stores.io.upstream.response <> lsu.io.memory.response
        } else {
            stores.io.upstream <> lsu.io.memory
        }
        stores.io.fastStore.valid := fastStoreValid
        stores.io.fastStore.bits := fastStoreRequest
        fastStoreReady := stores.io.fastStore.ready
        integerMemory <> stores.io.memory
        integerMemoryBusy := lsu.io.busy || stores.io.busy
        io.memoryForwarded := lsu.io.forwarded || stores.io.forwarded
        storeBufferStallCause := stores.io.requestStallCause
    } else {
        integerMemory <> lsu.io.memory
    }
    if (p.fpEnabled) {
        val fpMemory = systemUnit.get.io.fpMemory.get
        // Head system launch drains the complete integer path (including queued
        // buffered writes). Hold this exclusive owner through real retirement,
        // not just through its response, and prohibit younger LSU launches below.
        io.memory.request.valid := Mux(fpMemoryEpoch, fpMemory.request.valid, integerMemory.request.valid)
        io.memory.request.bits := Mux(fpMemoryEpoch, fpMemory.request.bits, integerMemory.request.bits)
        fpMemory.request.ready := fpMemoryEpoch && io.memory.request.ready
        integerMemory.request.ready := !fpMemoryEpoch && io.memory.request.ready
        fpMemory.response.valid := fpMemoryEpoch && io.memory.response.valid
        fpMemory.response.bits := io.memory.response.bits
        integerMemory.response.valid := !fpMemoryEpoch && io.memory.response.valid
        integerMemory.response.bits := io.memory.response.bits
        io.memory.response.ready := Mux(fpMemoryEpoch, fpMemory.response.ready, integerMemory.response.ready)
        io.memoryBusy := integerMemoryBusy || systemUnit.get.io.fpMemoryBusy.get || io.externalPrefetchBusy.getOrElse(false.B)
        when(fpMemoryEpoch) { assert(!integerMemoryBusy, "integer memory drained before FP ownership") }
    } else {
        io.memory <> integerMemory
    }
    for (lane <- 0 until p.renameWidth) {
        ledger.io.allocate(lane).valid := io.allocate(lane).valid
        ledger.io.allocate(lane).bits  := io.allocate(lane).bits.rename
    }
    ledger.io.dispatchReady       := !emptyTrap // One reservation slot per ROB entry guarantees capacity.
    ledger.io.commitEnable        := io.commitEnable && !branchRetirementHold && !replayRetirementHold
    ledger.io.recoveryProbe       := recovery
    ledger.io.recoveryProbe.valid := recovery.valid && !memoryProtected && !systemProtected
    ledger.io.inspectRegister     := io.inspectRegister
    io.renamed                    := ledger.io.renamed
    io.commit                     := ledger.io.commit
    io.recovering                 := ledger.io.recovering
    io.occupancy                  := ledger.io.occupancy
    io.headProfile.valid          := ledger.io.headValid
    io.headProfile.done           := ledger.io.headDone
    io.headProfile.pc             := ledger.io.headPc
    io.headException              := ledger.io.headException

    val values = if (!p.lvtPhysicalRegisterFile)
        Some(RegInit(VecInit(Seq.fill(p.physicalRegs)(0.U(64.W))))) else None
    val physicalReads = scala.collection.mutable.ArrayBuffer.empty[(UInt, UInt)]
    val physicalWrites = if (p.lvtPhysicalRegisterFile) Some(Wire(Vec(p.completionWidth, Valid(new Bundle {
        val address = UInt(p.physBits.W)
        val data = UInt(64.W)
    })))) else None
    physicalWrites.foreach(_.foreach { port => port.valid := false.B; port.bits := 0.U.asTypeOf(port.bits) })
    def readPhysical(index: UInt): UInt = if (p.lvtPhysicalRegisterFile) {
        val result = Wire(UInt(64.W))
        physicalReads += ((index, result))
        result
    } else values.get(index)
    val ready         = RegInit(VecInit((0 until p.physicalRegs).map(i => (i < 32).B)))
    val readyUpdate = if (p.parallelPrfReadyUpdates)
        Some(Module(new PhysicalReadyUpdate(p.physicalRegs, p.completionWidth + 1, p.renameWidth))) else None
    readyUpdate.foreach { update =>
        update.io.current := ready.asUInt
        for (r <- 0 until p.physicalRegs) { ready(r) := update.io.next(r) }
    }
    val pending       = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val memoryLive    = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val memoryCanonical = if (p.virtualRamLoadPrecheck)
        Some(RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))) else None
    val storeAddressKnown = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val storePrepared = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val storePreparationBusy = if (p.earlyStorePreparation)
        Some(RegInit(0.U(p.robEntries.W))) else None
    // Exact static class facts at allocation, not assumptions about decoded
    // opcodes. Bit 0 is the ordinary-store class; bit 1 additionally excludes
    // control flow during a held redirect. Readiness/grants remain live.
    val storePreparationKinds = if (p.earlyStorePreparation)
        Some(Reg(Vec(p.robEntries, UInt(2.W)))) else None
    // Keep prepared store bounds out of the younger-load issue decision path.
    val storeAddress   = Reg(Vec(p.robEntries, UInt(64.W)))
    val storeByteLanes = Reg(Vec(p.robEntries, UInt(8.W)))
    val storeSafeRange = Reg(Vec(p.robEntries, Bool()))
    val storeData      = Reg(Vec(p.robEntries, UInt(64.W)))
    val loadBeat      = Reg(Vec(p.robEntries, UInt(61.W)))
    val loadLanes     = Reg(Vec(p.robEntries, UInt(8.W)))
    val orderCheckValid = RegInit(false.B)
    val orderCheckIndex = RegInit(0.U(p.robBits.W))
    val orderCheckBeat  = Reg(UInt(61.W))
    val orderCheckLanes = Reg(UInt(8.W))
    val replayPendingValid = if (p.registeredLoadReplay) Some(RegInit(false.B)) else None
    val replayPending = if (p.registeredLoadReplay) Some(Reg(new FrontendRedirect(p))) else None
    val queue         = Reg(Vec(p.robEntries, new IntegerIssueEntry(p)))
    val queuedSourceDecode = if (p.sharedPhysicalSourceDecode && !p.lvtPhysicalRegisterFile)
        Some(Module(new QueuedPhysicalSourceDecode(p))) else None
    queuedSourceDecode.foreach { decode =>
        for (slot <- 0 until p.robEntries) {
            decode.io.source1(slot) := queue(slot).renamed.source1
            decode.io.source2(slot) := queue(slot).renamed.source2
        }
    }
    def independentPhysicalOperands(): IssuePhysicalOperands = {
        val operands = Module(new IssuePhysicalOperands(p, sharedSourceDecode = p.sharedPhysicalSourceDecode && !p.lvtPhysicalRegisterFile))
        queuedSourceDecode.foreach { decode =>
            operands.io.decoded1.get := decode.io.decoded1
            operands.io.decoded2.get := decode.io.decoded2
        }
        // Existing call sites still connect their own early owners, source IDs
        // and PRF values. Store/M-D/LSU reads NEVER share a late grant/value mux.
        if (p.lvtPhysicalRegisterFile) {
            operands.io.values := 0.U.asTypeOf(operands.io.values)
            for (port <- 0 until 4) operands.io.readData.get(port) := readPhysical(operands.io.readAddress.get(port))
        }
        operands
    }
    val ownerReady = if (p.ownerLocalOperandReady)
        Some(Module(new OwnerOperandReady(p, precomputedAllocationReady = p.tentativeRenameSources))) else None
    ownerReady.foreach { mirror =>
        mirror.io.physical := ready.asUInt
        mirror.io.active := pending.asUInt
        mirror.io.wake := readyUpdate.get.io.wake
        mirror.io.reserve := readyUpdate.get.io.reserve
        if (p.tentativeRenameSources) {
            // These candidate ID reads start before PMP/fault selection. Keep
            // the original accepted wake/reserve events, then select Booleans.
            val initialization = Module(new FaultAwareAllocationReady(p))
            initialization.io.sources := ledger.io.sourceCandidates.get
            initialization.io.faults := io.fetchFaultMask.get
            initialization.io.physical := ready.asUInt
            initialization.io.wake := readyUpdate.get.io.wake
            initialization.io.reserve := readyUpdate.get.io.reserve
            mirror.io.allocationReady1.get := initialization.io.ready1
            mirror.io.allocationReady2.get := initialization.io.ready2
        }
        for (slot <- 0 until p.robEntries) {
            mirror.io.source1(slot) := queue(slot).renamed.source1
            mirror.io.source2(slot) := queue(slot).renamed.source2
        }
        for (lane <- 0 until p.renameWidth) {
            val renamed = ledger.io.renamed(lane)
            mirror.io.allocate(lane).valid := renamed.valid
            mirror.io.allocate(lane).bits.index := renamed.bits.token.index
            mirror.io.allocate(lane).bits.source1 := renamed.bits.source1
            mirror.io.allocate(lane).bits.source2 := renamed.bits.source2
        }
    }
    io.committedValue := Mux(io.inspectRegister === 0.U, 0.U, readPhysical(ledger.io.committedMapping))

    // Recovery removes tails, so the head advances only on commit. Slot age needs robBits, not a full tag compare.
    val head = RegInit(0.U(p.robBits.W))
    val acceptedCommits = PopCount(ledger.io.commit.map(_.valid))
    head := head + acceptedCommits
    val issueHeadMask = if (p.registeredIssueHeadMask) {
        val boundary = Module(new RegisteredRobHeadMask(p))
        boundary.io.head := head
        boundary.io.commits := acceptedCommits
        Some(boundary.io.afterHead)
    } else None
    val headRequest = queue(head).request
    val headRenamed = queue(head).renamed
    // A completed load has its result in the LSU register before the completion arbiter writes
    // the physical register. Wake dependent ALU work from that stable result to avoid a CDB cycle.
    val completedLoadIndex = lsu.io.complete.bits.token.index
    val completedLoadEntry = queue(completedLoadIndex)
    val completedLoadBypass = p.loadCompletionBypass.B && lsu.io.complete.valid &&
        !lsu.io.complete.bits.exception &&
        memoryLive(completedLoadIndex) &&
        completedLoadEntry.renamed.token.asUInt === lsu.io.complete.bits.token.asUInt &&
        completedLoadEntry.request.memory && !completedLoadEntry.request.store &&
        !completedLoadEntry.request.atomic && completedLoadEntry.renamed.writesRd
    val wordPreviewBypass = p.mulWordPreviewBypass.B && multiplier.io.wordPreview.valid &&
        !multiplier.io.wordPreview.bits.exception &&
        queue(multiplier.io.wordPreview.bits.token.index).renamed.token.asUInt ===
            multiplier.io.wordPreview.bits.token.asUInt &&
        queue(multiplier.io.wordPreview.bits.token.index).renamed.writesRd
    val wordPreviewDestination = queue(multiplier.io.wordPreview.bits.token.index).renamed.destination
    // A speculative ordinary-ALU availability promise comes from REGISTERED
    // ownership/legality, not same-cycle cancellation. It only selects/captures
    // next-cycle operand data; it never writes the PRF, ROB or ready scoreboard.
    // Every actual capture/completion is separately authorized by current kill.
    // A killed producer's younger dependants must be killed at that same edge.
    // Memory/M-unit scheduling retains the original registered ready file.
    val executionWake = Wire(Vec(p.completionWidth, Valid(UInt(p.physBits.W))))
    val executionData = Wire(Vec(p.completionWidth, UInt(64.W)))
    executionWake.foreach { wake => wake.valid := false.B; wake.bits := 0.U }
    executionData.foreach(_ := 0.U)
    def operandReady(index: UInt): Bool = ready(index) ||
        (completedLoadBypass && index === completedLoadEntry.renamed.destination) ||
        (wordPreviewBypass && index === wordPreviewDestination)
    def operandValue(index: UInt): UInt = Mux(
        completedLoadBypass && index === completedLoadEntry.renamed.destination,
        lsu.io.complete.bits.data,
        Mux(wordPreviewBypass && index === wordPreviewDestination,
            multiplier.io.wordPreview.bits.data, readPhysical(index)))
    val loadIssueWake = lsu.io.completedIssueDestination.getOrElse(0.U.asTypeOf(Valid(UInt(p.physBits.W))))
    // Only registered LSU completion state/metadata feeds this promise. Current
    // recovery, completion acceptance and ROB tag comparisons are authorization
    // checks below, not feedback into speculative wake/ranking.
    def loadIssueHit(index: UInt): Bool = loadIssueWake.valid && loadIssueWake.bits === index
    def issueOperandReady(index: UInt): Bool = operandReady(index) || loadIssueHit(index) ||
        executionWake.map(wake => wake.valid && wake.bits === index).reduce(_ || _)
    def issueOperandValue(index: UInt, stored: UInt): UInt = {
        val hits = executionWake.map(wake => wake.valid && wake.bits === index)
        Mux(loadIssueHit(index), lsu.io.complete.bits.data,
            Mux(hits.reduce(_ || _), Mux1H(hits.zip(executionData)), stored))
    }
    if (p.registeredLoadIssueForwarding) {
        // Invalid completion payload is unspecified (including its index). A when
        // does not prevent combinational assertion expressions being evaluated.
        val promisedIndex = Mux(loadIssueWake.valid, lsu.io.complete.bits.token.index, 0.U)
        val promisedEntry = queue(promisedIndex)
        when(loadIssueWake.valid) {
            // Assertions intentionally inspect full ownership outside the wake cone.
            assert(memoryLive(promisedIndex) &&
                promisedEntry.renamed.token.asUInt === lsu.io.complete.bits.token.asUInt &&
                promisedEntry.renamed.destination === loadIssueWake.bits &&
                promisedEntry.renamed.writesRd && promisedEntry.request.memory &&
                !promisedEntry.request.store && !promisedEntry.request.atomic,
                "registered load forwarding metadata must match the live full-token owner")
            for (wake <- executionWake) {
                assert(!(wake.valid && wake.bits === loadIssueWake.bits),
                    "ALU and load promises cannot own the same physical destination")
            }
        }
    }
    io.headProfile.queued := ledger.io.headValid && pending(head)
    io.headProfile.operandsReady := ledger.io.headValid &&
        (headRequest.usePc || operandReady(headRenamed.source1)) &&
        ((headRequest.useImmediate && !headRequest.store && !headRequest.atomic) ||
            operandReady(headRenamed.source2))
    io.headProfile.memory := ledger.io.headValid && headRequest.memory
    io.headProfile.memoryRequestSelected := lsu.io.requestOwner.valid &&
        lsu.io.requestOwner.bits.asUInt === headRenamed.token.asUInt
    io.headProfile.memoryRequestStallCause := Mux(io.headProfile.memoryRequestSelected,
        storeBufferStallCause, 0.U)
    io.headProfile.memoryPhase := Mux1H((0 until p.memoryEntries).map { i =>
        (lsu.io.live(i) && lsu.io.owner(i).asUInt === headRenamed.token.asUInt) -> lsu.io.phase(i)
    })
    io.headProfile.memoryCompletionBlocked := io.headProfile.memory && !io.headProfile.queued &&
        io.headProfile.memoryPhase === 3.U &&
        !(lsu.io.complete.fire && lsu.io.complete.bits.token.asUInt === headRenamed.token.asUInt)
    val ages        = (0 until p.robEntries).map(i => i.U(p.robBits.W) - head)
    val boundaryAge = ledger.io.recover.bits.token.index - head

    // Accepted redirects immediately remove all killed reservation slots, even while RAT rollback continues.
    // The ROB has already authorized the boundary token. Pending slots are live, so modulo age suffices here.
    val killed   = Wire(Vec(p.robEntries, Bool()))
    val eligible = Wire(Vec(p.robEntries, Bool()))
    for (i <- 0 until p.robEntries) {
        val entry = queue(i)
        killed(i) := ledger.io.parallelRecovery.map(_.killed(i)).getOrElse(
            ledger.io.recoveryAccepted && (ages(i) > boundaryAge ||
                (ledger.io.recover.bits.inclusive && i.U === ledger.io.recover.bits.token.index)))
        // Selection must not depend on its own branch resolution. Authorization below suppresses killed results.
        val prepareStore = entry.request.memory && entry.request.store && !storePrepared(i) && i.U =/= head
        val source1 = Mux(pending(i), entry.renamed.source1, 0.U)
        val source2 = Mux(pending(i), entry.renamed.source2, 0.U)
        // Store preparation still computes its address in this cycle. Do not
        // concatenate the producer's ALU and that address adder through bypass.
        val source1Ready = entry.request.usePc || Mux(entry.request.memory,
            ownerReady.map(_.io.ready1(i)).getOrElse(operandReady(source1)), issueOperandReady(source1))
        val source2Ready = entry.request.useImmediate || Mux(entry.request.memory,
            ownerReady.map(_.io.ready2(i)).getOrElse(operandReady(source2)), issueOperandReady(source2))
        val readyToExecute = pending(i) && !entry.request.system && !entry.request.mulDiv &&
            (!entry.request.memory || prepareStore) && source1Ready &&
            (source2Ready || (prepareStore && !storeAddressKnown(i)))
        eligible(i) := readyToExecute && !storePreparationBusy.map(_(i)).getOrElse(false.B)
        when(killed(i)) {
            pending(i) := false.B
            memoryLive(i) := false.B
            memoryCanonical.foreach(_(i) := false.B)
            storeAddressKnown(i) := false.B
            storePrepared(i) := false.B
        }
        when(ledger.io.commit.map(c => c.valid && c.bits.token.index === i.U).reduce(_ || _)) {
            memoryLive(i)    := false.B
            memoryCanonical.foreach(_(i) := false.B)
            storeAddressKnown(i) := false.B
            storePrepared(i) := false.B
        }
    }

    class Candidate extends Bundle {
        val valid = Bool()
        val index = UInt(p.robBits.W)
        val age   = UInt(p.robBits.W)
    }
    def tournament(items: Seq[Candidate]): Candidate = {
        if (items.size == 1) items.head
        else
            tournament(
                items
                    .grouped(2)
                    .map {
                        case Seq(a, b) => Mux(a.valid && (!b.valid || a.age < b.age), a, b)
                        case Seq(a)    => a
                    }
                    .toSeq
            )
    }
    val virtualized = if (p.virtualMemoryLevels > 0)
        dataPrivilege =/= 3.U && systemUnit.get.io.vmState.get.satp(63, 60) =/= 0.U
    else false.B
    val fastAddress = storeAddress(head)
    // The head queue slot is uninitialized before allocation. Keep shift amounts defined
    // even while this optimization is inactive (GSIM evaluates both sides of comparisons).
    val fastSize = Mux(ledger.io.headValid && pending(head), headRequest.memorySize, 0.U)
    val fastAligned = (fastAddress(2, 0) & ((1.U << fastSize) - 1.U)) === 0.U
    val fastRam = SpeculativeRamRange.contains(p, fastAddress, fastSize)
    val fastPmp = Module(new PmpChecker(p.pmpEntries))
    fastPmp.io.state := pmpState
    fastPmp.io.address := fastAddress
    fastPmp.io.size := fastSize
    fastPmp.io.privilege := dataPrivilege
    fastPmp.io.access := PmpAccess.write
    val fastStoreCandidate = p.fastBufferedStoreRetire.B && p.bufferedRamStores.B &&
        ledger.io.headValid && !ledger.io.headDone && pending(head) &&
        headRequest.memory && headRequest.store && !headRequest.atomic && storePrepared(head) &&
        fastAligned && fastRam && !virtualized && !fastPmp.io.denied &&
        io.commitEnable && !interruptDrain && !reserveSystem && !memoryProtected && !systemProtected &&
        !ledger.io.recovering
    fastStoreValid := fastStoreCandidate && !ledger.io.recoveryAccepted && !ledger.io.headException.valid
    fastStoreRequest.address := fastAddress
    fastStoreRequest.size := fastSize
    fastStoreRequest.data := storeData(head) << Cat(fastAddress(2, 0), 0.U(3.W))
    fastStoreRequest.mask := byteLanes(fastSize, fastAddress)
    fastStoreRequest.write := true.B
    // Selection reserves capacity before redirect resolution; the actual write is suppressed on recovery.
    val directStoreReserve = fastStoreCandidate && fastStoreReady
    val directStoreFire = fastStoreValid && fastStoreReady
    val stagedMemoryValid = if (p.registeredMemoryAddress) Some(RegInit(false.B)) else None
    val stagedMemoryIndex = if (p.registeredMemoryAddress) Some(RegInit(0.U(p.robBits.W))) else None
    val stagedMemoryToken = if (p.registeredMemoryAddress) Some(Reg(new RobToken(p))) else None
    val stagedMemoryAddress = if (p.registeredMemoryAddress) Some(Reg(UInt(64.W))) else None
    val stagedMemoryData = if (p.registeredMemoryAddress) Some(Reg(UInt(64.W))) else None
    // Transfer size is payload, not a liveness decision. Capture it with the
    // already staged address instead of letting a late token comparison feed
    // RAM/PMP/byte-lane decoders. Reset keeps invalid GSIM shift operands defined.
    val stagedMemorySize = if (p.registeredMemoryAddress) Some(RegInit(0.U(2.W))) else None
    val memoryIssued = WireDefault(false.B)
    val memoryCandidates = (0 until p.robEntries).map { i =>
        val c            = Wire(new Candidate)
        val entry        = queue(i)
        // Invalid queue slots are uninitialized. Do not use their stale IDs to
        // address the compact (48-entry, not 64-entry) PRF in the new planner.
        val source1 = if (p.parallelMemoryPreparation) Mux(pending(i), entry.renamed.source1, 0.U)
            else entry.renamed.source1
        val source2 = if (p.parallelMemoryPreparation) Mux(pending(i), entry.renamed.source2, 0.U)
            else entry.renamed.source2
        val sourcesReady = ownerReady.map(_.io.ready1(i)).getOrElse(operandReady(source1)) &&
            (!(entry.request.store || entry.request.atomic) ||
                ownerReady.map(_.io.ready2(i)).getOrElse(operandReady(source2)))
        c.valid := pending(i) && entry.request.memory && (!entry.request.store || i.U === head) &&
            !(directStoreReserve && i.U === head) &&
            !(if (p.registeredMemoryAddress && !p.parallelMemoryPreparation)
                memoryIssued && i.U === stagedMemoryIndex.get else false.B) &&
            (storePrepared(i) || sourcesReady)
        c.index := i.U
        c.age   := ages(i)
        c
    }
    val memoryPrechoice = tournament(memoryCandidates)
    val memoryChoice = Wire(new Candidate)
    if (p.registeredMemoryAddress) {
        if (p.parallelMemoryPreparation) {
            val planner = Module(new MemoryPreparationSelector(p, parallelRanks = p.parallelMemoryPayload,
                predecodedHead = p.registeredIssueHeadMask))
            planner.io.eligible := VecInit(memoryCandidates.map(_.valid)).asUInt
            planner.io.head := head
            planner.io.headMask.foreach(_ := issueHeadMask.get)
            planner.io.issued := memoryIssued
            planner.io.issuedIndex := stagedMemoryIndex.get
            // Only LSU preparation uses the compact binary source selection.
            // Rank owners choose two small source IDs, not 48 x 16 match masks;
            // store/M-D/ALU ports and late grant exclusion remain independent.
            val memoryOperands = if (p.parallelMemoryPayload && !p.compactMemoryOperandSelect)
                Some(independentPhysicalOperands()) else None
            memoryOperands.foreach { operands =>
                operands.io.owners(0) := planner.io.firstOwner
                operands.io.owners(1) := planner.io.secondOwner
                if (!p.lvtPhysicalRegisterFile) operands.io.values := values.get
                for (slot <- 0 until p.robEntries) {
                    operands.io.source1(slot) := queue(slot).renamed.source1
                    operands.io.source2(slot) := queue(slot).renamed.source2
                }
            }
            val candidates = Seq((planner.io.firstValid, planner.io.firstIndex),
                (planner.io.secondValid, planner.io.secondIndex)).zipWithIndex.map { case ((valid, index), rank) =>
                val owner = if (rank == 0) planner.io.firstOwner else planner.io.secondOwner
                def selected(payloads: Seq[UInt]): UInt = CircularIssueSelector.selectPayload(owner, payloads)
                val entry = if (p.parallelMemoryPayload)
                    selected(queue.map(_.asUInt).toSeq).asTypeOf(new IntegerIssueEntry(p)) else queue(index)
                val saved = valid && entry.request.store && (if (p.parallelMemoryPayload)
                    (owner & storePrepared.asUInt).orR else storePrepared(index))
                val source1 = Mux(valid, entry.renamed.source1, 0.U)
                val source2 = Mux(valid, entry.renamed.source2, 0.U)
                val savedAddress = if (p.parallelMemoryPayload) selected(storeAddress.toSeq) else storeAddress(index)
                val savedData = if (p.parallelMemoryPayload) selected(storeData.toSeq) else storeData(index)
                val left = memoryOperands.map(_.io.left(rank)).getOrElse(operandValue(source1))
                val right = memoryOperands.map(_.io.right(rank)).getOrElse(operandValue(source2))
                val summed = if (p.parallelMemoryAddressSum)
                    TimingArithmetic.add64(left, entry.request.immediate) else left + entry.request.immediate
                val address = Mux(saved, savedAddress, summed)
                val data = Mux(saved, savedData, right)
                (entry.renamed.token, address, data, entry.request.memorySize)
            }
            // The late start.fire only selects fully computed payloads. It must
            // not choose a PRF port or enter the 64-bit effective-address adder.
            stagedMemoryValid.get := planner.io.selectedValid
            when(planner.io.selectedValid) {
                stagedMemoryIndex.get := planner.io.selectedIndex
            }
            // Invalid payloads cannot authorize a request: valid, owner token,
            // and pending still gate every use. Avoid a late 64-bit clock enable.
            when(planner.io.selectedValid || p.unconditionalMemoryPayloadCapture.B) {
                stagedMemoryToken.get := Mux(planner.io.useSecond, candidates(1)._1, candidates(0)._1)
                stagedMemoryAddress.get := Mux(planner.io.useSecond, candidates(1)._2, candidates(0)._2)
                stagedMemoryData.get := Mux(planner.io.useSecond, candidates(1)._3, candidates(0)._3)
                stagedMemorySize.get := Mux(planner.io.useSecond, candidates(1)._4, candidates(0)._4)
            }
        } else {
            val preparation = queue(memoryPrechoice.index)
            val saved = memoryPrechoice.valid && preparation.request.store && storePrepared(memoryPrechoice.index)
            val source1 = Mux(memoryPrechoice.valid, preparation.renamed.source1, 0.U)
            val source2 = Mux(memoryPrechoice.valid, preparation.renamed.source2, 0.U)
            stagedMemoryValid.get := memoryPrechoice.valid
            when(memoryPrechoice.valid) {
                stagedMemoryIndex.get := memoryPrechoice.index
                stagedMemoryToken.get := preparation.renamed.token
                stagedMemoryAddress.get := Mux(saved, storeAddress(memoryPrechoice.index),
                    operandValue(source1) + preparation.request.immediate)
                stagedMemoryData.get := Mux(saved, storeData(memoryPrechoice.index), operandValue(source2))
                stagedMemorySize.get := preparation.request.memorySize
            }
        }
        memoryChoice.valid := stagedMemoryValid.get && pending(stagedMemoryIndex.get) &&
            queue(stagedMemoryIndex.get).renamed.token.asUInt === stagedMemoryToken.get.asUInt
        memoryChoice.index := stagedMemoryIndex.get
        memoryChoice.age := stagedMemoryIndex.get - head
    } else {
        memoryChoice := memoryPrechoice
    }
    val memoryEntry   = queue(memoryChoice.index)
    val memorySize    = stagedMemorySize.getOrElse(Mux(memoryChoice.valid, memoryEntry.request.memorySize, 0.U))
    val memorySource1 = Mux(memoryChoice.valid, memoryEntry.renamed.source1, 0.U)
    val memorySource2 = Mux(memoryChoice.valid, memoryEntry.renamed.source2, 0.U)
    val savedStore    = memoryChoice.valid && memoryEntry.request.store && storePrepared(memoryChoice.index)
    val address       = if (p.registeredMemoryAddress) stagedMemoryAddress.get else
        Mux(savedStore, storeAddress(memoryChoice.index), operandValue(memorySource1) + memoryEntry.request.immediate)
    val loadPreparation = if (p.virtualRamLoadPrecheck) Some(Module(new VirtualRamLoadPreparation(p))) else None
    loadPreparation.foreach { preparation =>
        preparation.io.precheck <> io.loadPrecheck.get
        preparation.io.candidate.valid := memoryChoice.valid && virtualized &&
            !memoryEntry.request.store && !memoryEntry.request.atomic
        preparation.io.candidate.bits.token := memoryEntry.renamed.token
        preparation.io.candidate.bits.address := address
        preparation.io.candidate.bits.size := memorySize
        preparation.io.pmpState := pmpState
        preparation.io.privilege := dataPrivilege
        // Do not feed same-cycle branch resolution into reservation selection. Full token/pending checks
        // and the existing LSU launch recovery gate reject same-edge kills; rollback clears the proof.
        preparation.io.flush := ledger.io.recovering || contextMemoryEpoch || interruptDrain || reserveSystem
    }
    val preparedLoadMatches = loadPreparation.map { preparation =>
        val result = preparation.io.prepared
        result.valid && memoryChoice.valid && result.bits.token.asUInt === memoryEntry.renamed.token.asUInt &&
            result.bits.address === address && result.bits.size === memorySize
    }.getOrElse(false.B)
    val precheckedLoad = preparedLoadMatches && virtualized &&
        !memoryEntry.request.store && !memoryEntry.request.atomic &&
        loadPreparation.map(_.io.prepared.bits.allowed).getOrElse(false.B)
    // Preparation is opportunistic. A ready head never waits for an optional certificate: it uses
    // the existing serial virtual path unless a matching registered proof is already available.
    // Only younger speculation requires a positive proof. This preserves cold/dependent head-load
    // latency without a combinational TLB/PMP bypass. A serial start clears pending below, so a
    // later proof for that full token cannot relaunch it or change the accepted LSU owner's mode.
    val canonicalAddress = Mux(virtualized,
        loadPreparation.map(_.io.prepared.bits.physicalAddress).getOrElse(address), address)
    val pmpCheck = Module(new PmpChecker(p.pmpEntries))
    pmpCheck.io.state     := pmpState
    pmpCheck.io.address   := address
    pmpCheck.io.size      := memorySize
    pmpCheck.io.privilege := dataPrivilege
    pmpCheck.io.access    := Mux(memoryEntry.request.atomic,
        Mux(memoryEntry.request.atomicOp === 2.U, PmpAccess.read,
            Mux(memoryEntry.request.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
        Mux(memoryEntry.request.store, PmpAccess.write, PmpAccess.read))
    val ordinaryRam = (!virtualized && SpeculativeRamRange.contains(p, address, memorySize)) || precheckedLoad
    val sourceStore                                = lsu.io.forwardStore
    def byteLanes(size: UInt, address: UInt): UInt = {
        val mask = MuxLookup(size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
        (mask << address(2, 0))(7, 0)
    }
    val loadMask  = byteLanes(memorySize, canonicalAddress)
    val loadAligned = AlignedMemoryDisjoint.aligned(canonicalAddress, memorySize)
    val storeMask = byteLanes(sourceStore.bits.size, sourceStore.bits.address)
    val sourceRam = SpeculativeRamRange.contains(p, sourceStore.bits.address, sourceStore.bits.size)
    val forwarding =
        sourceStore.valid && sourceRam && ordinaryRam && !precheckedLoad && !memoryEntry.request.store && !memoryEntry.request.atomic &&
            sourceStore.bits.address(63, 3) === canonicalAddress(63, 3) && (storeMask & loadMask) === loadMask &&
            memoryLive(sourceStore.bits.token.index) &&
            (sourceStore.bits.token.index - head) < memoryChoice.age
    val physicalStoreConflict = (0 until p.robEntries)
        .map { i =>
            // Safe prepared stores and naturally aligned loads are single-beat
            // byte intervals. Unaligned younger loads wait for precise head
            // fault handling; they cannot use a truncated lane mask to bypass.
            val disjoint = AlignedMemoryDisjoint.withLanes(canonicalAddress, loadAligned, loadMask,
                storeAddress(i)(63, 3), storeByteLanes(i))
            memoryLive(i) && queue(i).request.store && ages(i) < memoryChoice.age &&
            !(storeAddressKnown(i) && storeSafeRange(i) && disjoint) &&
            !(forwarding && queue(i).renamed.token.asUInt === sourceStore.bits.token.asUInt)
        }
        .reduce(_ || _)
    // Initial virtual overlap never guesses an older store's PA or compares a VA with a PA.
    // Unknown/unissued older memory must establish canonical ownership before a younger proof can launch.
    val olderUncanonicalMemory = memoryCanonical.map { known =>
        (0 until p.robEntries).map(i => memoryLive(i) && ages(i) < memoryChoice.age &&
            (queue(i).request.store || !known(i))).reduce(_ || _)
    }.getOrElse(false.B)
    val blockedByStore = physicalStoreConflict || (precheckedLoad && olderUncanonicalMemory)
    val unknownOlderStore = (0 until p.robEntries)
        .map(i => memoryLive(i) && queue(i).request.store && ages(i) < memoryChoice.age && !storeAddressKnown(i))
        .reduce(_ || _)
    val speculative = !memoryEntry.request.store && !memoryEntry.request.atomic && ordinaryRam
    // Reserve before branch resolution to avoid a select -> redirect -> select combinational loop.
    val olderSystem = (0 until p.robEntries)
        .map(i =>
            ((pending(i) && queue(i).request.system) || (memoryLive(i) && queue(i).request.atomic)) &&
                ages(i) < memoryChoice.age
        )
        .reduce(_ || _)
    val reserveMemory =
        !interruptDrain && !reserveSystem && !olderSystem && !fpMemoryEpoch && !contextMemoryEpoch &&
            memoryChoice.valid && lsu.io.issueAvailable && io.commitEnable &&
            ((p.issueWidth > 1).B || !directStoreReserve) &&
            !ledger.io.recovering && (!memoryEntry.request.atomic || !io.memoryBusy) &&
            (if (p.registeredMemoryAddress) true.B else
                savedStore || (operandReady(memorySource1) &&
                    (!(memoryEntry.request.store || memoryEntry.request.atomic) || operandReady(memorySource2)))) &&
            (memoryChoice.index === head || (speculative && !blockedByStore))
    val youngerLoadCouldIssue = !interruptDrain && !reserveSystem && !olderSystem && !fpMemoryEpoch && !contextMemoryEpoch && memoryChoice.valid &&
        !memoryEntry.request.store && !memoryEntry.request.atomic && memoryChoice.index =/= head &&
        speculative && lsu.io.issueAvailable && io.commitEnable && !ledger.io.recovering &&
        !ledger.io.recoveryAccepted && !ledger.io.headException.valid && operandReady(memorySource1)
    io.headProfile.candidateLoadPc := memoryEntry.request.rename.pc
    io.headProfile.candidateLoadBlockedByStore := youngerLoadCouldIssue && blockedByStore
    io.headProfile.candidateLoadBlockedByUnknownStore := youngerLoadCouldIssue && blockedByStore &&
        unknownOlderStore
    // A younger RAM read may run while this older load's address is unavailable. Check its
    // address in the cycle after issue: even an immediately forwarded load cannot retire before
    // this check, so a conflict can still replay the oldest overlapping younger read precisely.
    // The register boundary removes address generation from the overlap/recovery path.
    // Aligned W/D/H/B loads lie within one 64-bit beat, so compare beat and byte lanes.
    val selectedLanes = byteLanes(memorySize, canonicalAddress)
    val replaySelector = Module(new LoadReplaySelector(p))
    replaySelector.io.head := head
    // This check runs exactly one cycle after issue; the owner cannot retire and reuse its ROB slot yet.
    replaySelector.io.checkedValid := orderCheckValid && memoryLive(orderCheckIndex)
    replaySelector.io.checkedIndex := orderCheckIndex
    replaySelector.io.checkedBeat := orderCheckBeat
    replaySelector.io.checkedLanes := orderCheckLanes
    replaySelector.io.beats := loadBeat
    replaySelector.io.lanes := loadLanes
    replaySelector.io.eligible := VecInit((0 until p.robEntries).map { i =>
        memoryLive(i) && !pending(i) && queue(i).request.memory &&
            !queue(i).request.store && !queue(i).request.atomic &&
            memoryCanonical.map(_(i)).getOrElse(true.B)
    }).asUInt
    val loadReplay = Wire(new Candidate)
    loadReplay.valid := replaySelector.io.valid
    loadReplay.index := replaySelector.io.index
    loadReplay.age := replaySelector.io.index - head
    val loadReplayToken = Mux1H((0 until p.robEntries).map { i =>
        replaySelector.io.oneHot(i) -> queue(i).renamed.token
    })
    val loadReplayPc = Mux1H((0 until p.robEntries).map { i =>
        replaySelector.io.oneHot(i) -> queue(i).request.rename.pc
    })
    if (p.registeredLoadReplay) {
        // The overlap is known one cycle after issue. Hold retirement while it is
        // checked and until any resulting redirect is presented to the ROB.
        replayRetirementHold := orderCheckValid || replayPendingValid.get
        replayPendingValid.get := loadReplay.valid
        when(loadReplay.valid) {
            replayPending.get.token := loadReplayToken
            replayPending.get.pc := loadReplayPc
            replayPending.get.target := loadReplayPc
        }
    }
    // A raw recovery candidate may be stale, but blocking an extra issue is safe. In
    // this optional mode the LSU launch no longer waits for ROB recovery authorization
    // (or for the accepted-recovery-dependent headException output).
    lsu.io.start.valid := reserveMemory &&
        !(if (p.earlyRecoveryIssueBlock) earlyRecoveryIssueBlock else ledger.io.recoveryAccepted) &&
        !(if (p.earlyRecoveryIssueBlock) ledger.io.pendingException.valid else ledger.io.headException.valid)
    memoryIssued                   := lsu.io.start.fire
    io.headProfile.storePrepared := ledger.io.headValid && headRequest.store && storePrepared(head)
    io.headProfile.memoryStarting := directStoreFire || (lsu.io.start.fire && memoryChoice.index === head)
    io.headProfile.memorySlotAvailable := lsu.io.issueAvailable
    lsu.io.parallel                 := speculative
    lsu.io.start.bits.forward.valid := forwarding
    lsu.io.start.bits.forward.bits  := sourceStore.bits.data
    lsu.io.issueDestination.foreach { destination =>
        destination.valid := memoryEntry.renamed.writesRd
        destination.bits := memoryEntry.renamed.destination
    }
    lsu.io.start.bits.token         := memoryEntry.renamed.token
    lsu.io.start.bits.pc            := memoryEntry.request.rename.pc
    lsu.io.start.bits.address       := address
    lsu.io.start.bits.precheckedLoad := precheckedLoad
    lsu.io.start.bits.physicalAddress := loadPreparation.map(_.io.prepared.bits.physicalAddress).getOrElse(0.U)
    lsu.io.start.bits.translationEpoch := loadPreparation.map(_.io.prepared.bits.epoch).getOrElse(0.U)
    lsu.io.start.bits.data          := (if (p.registeredMemoryAddress) stagedMemoryData.get else
        Mux(savedStore, storeData(memoryChoice.index), operandValue(memorySource2)))
    lsu.io.start.bits.atomic        := memoryEntry.request.atomic
    lsu.io.start.bits.atomicOp      := memoryEntry.request.atomicOp
    lsu.io.start.bits.store         := memoryEntry.request.store
    lsu.io.start.bits.size          := memorySize
    lsu.io.start.bits.unsigned      := memoryEntry.request.memoryUnsigned
    lsu.io.start.bits.accessDenied  := pmpCheck.io.denied && !virtualized
    lsu.io.start.bits.virtualized   := virtualized
    // Guaranteed RAM writes receive a local StoreBuffer acknowledgement with request acceptance.
    // Retire only the current head and only after that acceptance; the LSU discards its duplicate
    // registered completion. MMIO, atomics, faults and backpressured writes keep the normal path.
    val fastStoreRetire = p.fastBufferedStoreRetire.B && lsu.io.start.fire &&
        memoryChoice.index === head && memoryEntry.request.store && !memoryEntry.request.atomic &&
        ordinaryRam && !pmpCheck.io.denied && lsu.io.memory.request.fire &&
        lsu.io.memory.response.fire && !lsu.io.memory.response.bits.error &&
        !lsu.io.memory.response.bits.pageFault
    val fastLoadRetire = p.fastHeadLoadRetire.B && lsu.io.fastLoadPreview.valid &&
        ledger.io.headValid && headRequest.memory && !headRequest.store && !headRequest.atomic &&
        lsu.io.fastLoadPreview.bits.token.asUInt === headRenamed.token.asUInt &&
        !memoryProtected && !ledger.io.recovering && !ledger.io.recoveryAccepted &&
        !ledger.io.headException.valid && io.commitEnable
    lsu.io.fastStoreRetire := fastStoreRetire
    lsu.io.fastLoadRetire := fastLoadRetire
    val fastStoreCompletion = Wire(new BackendCompletion(p))
    fastStoreCompletion := 0.U.asTypeOf(new BackendCompletion(p))
    fastStoreCompletion.token := Mux(directStoreFire, headRenamed.token, memoryEntry.renamed.token)
    fastStoreCompletion.nextPc := Mux(directStoreFire, headRequest.rename.pc +
        Mux(p.compressedInstructions.B && headRequest.rename.instruction(1, 0) =/= 3.U, 2.U, 4.U),
        memoryEntry.request.rename.pc +
            Mux(p.compressedInstructions.B && memoryEntry.request.rename.instruction(1, 0) =/= 3.U, 2.U, 4.U))
    ledger.io.fastHeadRetire.valid := directStoreFire || fastStoreRetire || fastLoadRetire
    ledger.io.fastHeadRetire.bits := Mux(fastLoadRetire, lsu.io.fastLoadPreview.bits, fastStoreCompletion)
    for (slot <- 0 until p.memoryEntries) {
        lsu.io.cancel(slot) := lsu.io.live(slot) && killed(Mux(lsu.io.live(slot), lsu.io.owner(slot).index, 0.U))
    }
    orderCheckValid := lsu.io.start.fire && speculative
    when(lsu.io.start.fire) {
        when(precheckedLoad) {
            assert(preparedLoadMatches && (memoryChoice.index === head || !olderUncanonicalMemory),
                "a prechecked start requires its unchanged full-token certificate and canonical older memory")
        }
        pending(memoryChoice.index) := false.B
        memoryCanonical.foreach(_(memoryChoice.index) := !virtualized || precheckedLoad)
        loadBeat(memoryChoice.index)  := canonicalAddress(63, 3)
        loadLanes(memoryChoice.index) := selectedLanes
        orderCheckIndex := memoryChoice.index
        orderCheckBeat  := canonicalAddress(63, 3)
        orderCheckLanes := selectedLanes
        // An overlapping RAM start must not release the previous irrevocable owner's protection.
        when(!speculative) {
            memoryProtected := true.B
            memoryOwner     := memoryEntry.renamed.token
        }
    }
    when(directStoreFire) { pending(head) := false.B }
    when(
        lsu.io.complete.fire && lsu.io.complete.bits.exception &&
            lsu.io.complete.bits.token.asUInt === memoryOwner.asUInt
    ) { memoryProtected := false.B }
    when(ledger.io.commit.map(c => c.valid && c.bits.token.asUInt === memoryOwner.asUInt).reduce(_ || _)) {
        memoryProtected := false.B
    }
    when(fastStoreRetire) { memoryProtected := false.B }
    // ROB token checks discard stale completions. Always free the LSU result slot on presentation so
    // same-cycle recovery authorization cannot feed back through request and response readiness.
    lsu.io.complete.ready := true.B
    mulDiv.io.cancel      := mulDiv.io.busy && killed(Mux(mulDiv.io.busy, mulDiv.io.owner.index, 0.U))
    for (i <- 0 until multiplier.capacity) {
        multiplier.io.cancel(i) := multiplier.io.live(i) && killed(
            Mux(multiplier.io.live(i), multiplier.io.owner(i).index, 0.U)
        )
    }
    io.mulDivConcurrent  := mulDiv.io.busy && multiplier.io.live.reduce(_ || _)
    io.mulDivMultiCancel := PopCount(multiplier.io.cancel) >= 2.U
    io.mulDivCancelled   := mulDiv.io.cancel || multiplier.io.cancel.reduce(_ || _)
    io.mulDivBlocked     := (mulDiv.io.complete.valid && !mulDiv.io.complete.ready && !mulDiv.io.cancel) ||
        (multiplier.io.complete.valid && !multiplier.io.complete.ready)
    val mulDivChoice = Wire(new Candidate)
    val mulDivRequests = Wire(Vec(2, new MultiplyDivideRequest(p)))
    val mulDivGrants = Wire(Vec(2, Bool()))
    if (p.parallelMulDivDispatch) {
        // Each class owns an early payload port. Availability/cross-class age
        // selects only a grant, never a queue index, source ID, or DSP operand.
        val selector = Module(new SplitMulDivSelector(p, predecodedHead = p.registeredIssueHeadMask))
        selector.io.head := head
        selector.io.headMask.foreach(_ := issueHeadMask.get)
        selector.io.available := VecInit(Seq(multiplier.io.start.ready, mulDiv.io.start.ready))
        val operands = independentPhysicalOperands()
        operands.io.owners := selector.io.owner
        if (!p.lvtPhysicalRegisterFile) operands.io.values := values.get
        for (slot <- 0 until p.robEntries) {
            operands.io.source1(slot) := queue(slot).renamed.source1
            operands.io.source2(slot) := queue(slot).renamed.source2
        }
        for (kind <- 0 until 2) {
            selector.io.eligible(kind) := VecInit((0 until p.robEntries).map { i =>
                val source1 = Mux(pending(i), queue(i).renamed.source1, 0.U)
                val source2 = Mux(pending(i), queue(i).renamed.source2, 0.U)
                pending(i) && queue(i).request.mulDiv && queue(i).request.mulDivOp(2) === (kind == 1).B &&
                    ownerReady.map(_.io.ready1(i)).getOrElse(operandReady(source1)) &&
                    ownerReady.map(_.io.ready2(i)).getOrElse(operandReady(source2))
            }).asUInt
            val entry = CircularIssueSelector.selectPayload(selector.io.owner(kind), queue.map(_.asUInt).toSeq)
                .asTypeOf(new IntegerIssueEntry(p))
            mulDivRequests(kind).token := entry.renamed.token
            mulDivRequests(kind).pc := entry.request.rename.pc
            mulDivRequests(kind).operation := entry.request.mulDivOp
            mulDivRequests(kind).word := entry.request.word
            mulDivRequests(kind).left := operands.io.left(kind)
            mulDivRequests(kind).right := operands.io.right(kind)
            mulDivGrants(kind) := selector.io.grant(kind)
            when(selector.io.valid(kind)) {
                assert(entry.renamed.token.index === selector.io.index(kind),
                    "split M payload must belong to its independent ranked owner")
            }
        }
        mulDivChoice.valid := selector.io.selectedValid
        mulDivChoice.index := selector.io.selectedIndex
        mulDivChoice.age := selector.io.selectedIndex - head
    } else {
        mulDivChoice := tournament((0 until p.robEntries).map { i =>
            val c = Wire(new Candidate)
            c.valid := pending(i) && queue(i).request.mulDiv &&
                Mux(queue(i).request.mulDivOp(2), mulDiv.io.start.ready, multiplier.io.start.ready) &&
                operandReady(Mux(pending(i), queue(i).renamed.source1, 0.U)) &&
                operandReady(Mux(pending(i), queue(i).renamed.source2, 0.U))
            c.index := i.U
            c.age   := ages(i)
            c
        })
        val entry = queue(mulDivChoice.index)
        for (kind <- 0 until 2) {
            mulDivRequests(kind).token := entry.renamed.token
            mulDivRequests(kind).pc := entry.request.rename.pc
            mulDivRequests(kind).operation := entry.request.mulDivOp
            mulDivRequests(kind).word := entry.request.word
            mulDivRequests(kind).left := operandValue(Mux(mulDivChoice.valid, entry.renamed.source1, 0.U))
            mulDivRequests(kind).right := operandValue(Mux(mulDivChoice.valid, entry.renamed.source2, 0.U))
            mulDivGrants(kind) := mulDivChoice.valid && entry.request.mulDivOp(2) === (kind == 1).B
        }
    }
    val reserveMulDiv = mulDivChoice.valid && !reserveSystem && !reserveMemory &&
        ((p.issueWidth > 1).B || !directStoreReserve) && !ledger.io.recovering
    val mStart        = reserveMulDiv && !ledger.io.recoveryAccepted && !ledger.io.headException.valid
    mulDiv.io.start.valid          := mStart && mulDivGrants(1)
    multiplier.io.start.valid      := mStart && mulDivGrants(0)
    mulDiv.io.start.bits           := mulDivRequests(1)
    multiplier.io.start.bits      := mulDivRequests(0)
    when(mulDiv.io.start.fire || multiplier.io.start.fire) { pending(mulDivChoice.index) := false.B }
    mulDiv.io.complete.ready     := !lsu.io.complete.valid && ledger.io.completionAccepted(0)
    multiplier.io.complete.ready := !lsu.io.complete.valid && !mulDiv.io.complete.valid && ledger.io.completionAccepted(
        0
    )

    when(systemComplete.fire && systemComplete.bits.exception) { systemProtected := false.B }
    when(ledger.io.commit.map(c => c.valid && c.bits.token.asUInt === systemOwner.asUInt).reduce(_ || _)) {
        systemProtected := false.B
    }
    systemUnit.foreach { unit =>
        unit.io.fpRetire.foreach { retire =>
            val matches = ledger.io.commit.map(c => c.valid && c.bits.token.asUInt === systemOwner.asUInt)
            retire.valid := matches.reduce(_ || _)
            retire.bits := systemOwner
            assert(PopCount(matches) <= 1.U, "one real ROB retirement per protected FP owner")
        }
        pmpState := unit.io.pmpState
        dataPrivilege := unit.io.dataPrivilege
        io.pmpState.get       := unit.io.pmpState
        io.fetchPrivilege.get := unit.io.fetchPrivilege
        io.imsic.get <> unit.io.imsic
        unit.io.externalInterrupt           := io.externalInterrupt.get
        unit.io.supervisorExternalInterrupt := io.supervisorExternalInterrupt.get
        unit.io.timerInterrupt              := io.timerInterrupt.get
        unit.io.timeValue                   := io.timeValue.get
        io.fenceIFlush.get := unit.io.fenceIFlush
        unit.io.fenceIFlushReady := io.fenceIFlushReady.get
        interruptDrain                      := unit.io.interruptPending && !systemProtected
        val headPending = pending(head) && queue(head).request.system
        val headInst = Mux(p.compressedInstructions.B &&
            queue(head).request.rename.instruction(1, 0) =/= 3.U,
            queue(head).request.expandedInstruction, queue(head).request.rename.instruction)
        val headCsr = headInst(31, 20)
        val pmpHead = if (p.pmpEntries > 0)
            headPending && headInst(6, 0) === "h73".U && headInst(14, 12) =/= 0.U &&
                (headCsr === "h3a0".U || headCsr === "h3a2".U ||
                (headCsr >= "h3b0".U && headCsr < (0x3b0 + p.pmpEntries).U))
        else false.B
        val returnHead = headPending && (headInst === "h30200073".U || headInst === "h10200073".U)
        val vmHead = if (p.virtualMemoryLevels > 0) {
            val sfence = headInst(31, 25) === "b0001001".U && headInst(14, 7) === 0.U &&
                headInst(6, 0) === "h73".U
            val satpWrite = headInst(6, 0) === "h73".U && headInst(14, 12) =/= 0.U &&
                headCsr === "h180".U &&
                (headInst(13, 12) === 1.U || headInst(19, 15) =/= 0.U)
            headPending && (sfence || satpWrite)
        } else false.B
        val fenceIHead = headPending && headInst(6, 0) === "h0f".U && headInst(14, 12) === 1.U
        val drainFetch = pmpHead || returnHead || vmHead || fenceIHead
        if (p.pmpEntries > 0) {
            val barrierActive = RegInit(false.B)
            io.pauseFetch.get := drainFetch || barrierActive
            when(unit.io.start.fire && drainFetch) { barrierActive := true.B }
            when(systemComplete.fire) { barrierActive := false.B }
        }
        if (p.virtualMemoryLevels > 0) {
            io.vmState.get := unit.io.vmState.get
            io.vmFlush.get := unit.io.vmFlush.get
            unit.io.vmFlushReady.get := io.vmFlushReady.get
        }
        val source      = Mux(headPending, queue(head).renamed.source1, 0.U)
        reserveSystem := !unit.io.interruptPending && headPending && ready(
            source
        ) && unit.io.start.ready && io.commitEnable &&
            !io.memoryBusy && !ledger.io.recovering &&
            (if (p.pmpEntries > 0) !drainFetch || io.fetchQuiescent.get else true.B)
        unit.io.start.valid      := reserveSystem && !ledger.io.recoveryAccepted && !ledger.io.pendingException.valid
        unit.io.start.bits.token := queue(head).renamed.token
        unit.io.start.bits.pc    := queue(head).request.rename.pc
        unit.io.start.bits.instruction := headInst
        unit.io.start.bits.operand     := readPhysical(source)
        systemStart                    := unit.io.start.fire
        when(unit.io.start.fire) {
            systemFpMemory.foreach(_ := FloatingPointSubset.memory(headInst))
            systemContextBarrier := !(p.fpEnabled.B && FloatingPointDecode.supported(headInst, p.fpConfig) &&
                !FloatingPointDecode.memory(headInst))
            pending(head)   := false.B
            systemProtected := true.B
            systemOwner     := queue(head).renamed.token
        }
        systemComplete.valid   := unit.io.complete.valid
        systemComplete.bits    := unit.io.complete.bits.completion
        // Compressed FP memory uses the expanded encoding for execution, but
        // sequential retirement must retain the original two-byte instruction.
        if (p.compressedInstructions && p.fpEnabled) {
            val owner = queue(systemOwner.index).request
            when(FloatingPointDecode.memory(owner.expandedInstruction) &&
                owner.rename.instruction(1, 0) =/= 3.U && !unit.io.complete.bits.redirect) {
                systemComplete.bits.nextPc := owner.rename.pc + 2.U
            }
        }
        systemRedirect         := unit.io.complete.bits.redirect
        systemInvalidate       := unit.io.complete.valid && unit.io.complete.bits.invalidateFetch
        unit.io.complete.ready := systemComplete.ready
        val safeTrap = io.commitEnable && !io.memoryBusy && !systemProtected && !memoryProtected &&
            !ledger.io.recovering && unit.io.trapReady
        val interrupt = unit.io.interruptPending && !ledger.io.pendingException.valid
        automaticTrap := safeTrap && (ledger.io.pendingException.valid || interrupt)
        emptyTrap     := automaticTrap && ledger.io.occupancy === 0.U
        trapEvent     := ledger.io.pendingException.bits
        when(interrupt) {
            trapEvent.pc    := Mux(ledger.io.occupancy === 0.U, io.emptyPc.get, ledger.io.pendingException.bits.pc)
            trapEvent.cause := "h8000000000000000".U | unit.io.interruptCause
            trapEvent.tval  := 0.U
            when(ledger.io.occupancy === 0.U) { trapEvent.token := 0.U.asTypeOf(new RobToken(p)) }
        }
        if (p.fastHeadTrapRecovery) {
            // safeTrap and the synchronous-exception/IRQ choice above remain
            // authoritative. Only this known current-head inclusive request
            // may bypass ordinary token/age arbitration. Empty traps retain
            // the architectural emptyPc path and never fabricate a ROB owner.
            headTrapRequest := automaticTrap && !emptyTrap
            when(headTrapRequest) {
                assert(trapEvent.token.asUInt === headRenamed.token.asUInt,
                    "trusted automatic trap must identify the exact current head owner")
            }
        } else {
            when(automaticTrap && !emptyTrap) {
                recovery.valid          := true.B
                recovery.bits.token     := trapEvent.token
                recovery.bits.inclusive := true.B
            }
        }
        unit.io.trap.valid := automaticTrap && (emptyTrap ||
            (if (p.fastHeadTrapRecovery) headTrapAccepted else io.recoveryAccepted))
        unit.io.trap.bits  := trapEvent
        trapTarget         := unit.io.trapTarget
        io.trap.get        := unit.io.trap
    }
    val selected        = Wire(Vec(p.completionWidth, Valid(UInt(p.robBits.W))))
    val dispatched      = Wire(Vec(p.completionWidth, Valid(UInt(p.robBits.W))))
    val executionEnqueued = WireDefault(VecInit(Seq.fill(p.completionWidth)(false.B)))
    val prepared        = Wire(Vec(p.completionWidth, Bool()))
    val preparedOwners = Wire(Vec(p.completionWidth, UInt(p.robEntries.W)))
    val newResolutions  = Wire(Vec(p.completionWidth, Valid(new FrontendRedirect(p))))
    val completion      = Wire(Vec(p.completionWidth, new BackendCompletion(p)))
    val branchCandidate = Wire(Valid(new FrontendRedirect(p)))
    val branchRedirectValid = RegInit(false.B)
    val branchRedirect      = Reg(new FrontendRedirect(p))
    val branchResult        = Reg(new BackendCompletion(p))
    val branchResultPortFree = !lsu.io.complete.valid && !mCompleteValid &&
        !systemComplete.valid
    val branchRedirectReady = branchRedirectValid &&
        (if (p.precompleteMispredictedBranch) true.B else branchResultPortFree)
    val executionStages = if (p.registeredIssueExecute) Seq.fill(p.completionWidth) {
        Module(new IssueExecuteStage((new IntegerExecutionOperands(p)).getWidth))
    } else Seq.empty
    val executingOperands = executionStages.map(_.io.deq.bits.asTypeOf(new IntegerExecutionOperands(p)))
    for (lane <- executionStages.indices) {
        val stage = executionStages(lane)
        val entry = executingOperands(lane).entry
        val ownerIndex = Mux(stage.io.occupied, entry.renamed.token.index, 0.U)
        val stale = queue(ownerIndex).renamed.token.asUInt =/= entry.renamed.token.asUInt
        stage.io.cancel := stage.io.occupied && (killed(ownerIndex) || stale)
        stage.io.deq.ready := (if (lane == 0) branchResultPortFree else true.B) &&
            (!branchRedirectValid || entry.request.controlFlow === ControlFlow.none)
        when(stage.io.occupied) {
            assert(!stale,
                "an occupied execution slot owns its unchanged ROB token until consumption or same-edge cancellation")
        }
    }
    branchRetirementHold := p.precompleteMispredictedBranch.B && branchRedirectValid
    val localInclusive  = WireDefault(false.B)
    branchCandidate.valid := (if (p.registeredBranchRedirect) branchRedirectReady
        else newResolutions.map(_.valid).reduce(_ || _))
    // Keep an inactive candidate from indexing the ROB with undefined data.
    branchCandidate.bits := (if (p.registeredBranchRedirect)
        Mux(branchRedirectReady, branchRedirect, 0.U.asTypeOf(new FrontendRedirect(p)))
    else Mux(branchCandidate.valid, PriorityMux(newResolutions.map(r => r.valid -> r.bits)),
        0.U.asTypeOf(new FrontendRedirect(p))))
    val systemCandidate = WireDefault(0.U.asTypeOf(new FrontendRedirect(p)))
    systemCandidate.token := systemOwner
    systemCandidate.pc := queue(head).request.rename.pc
    systemCandidate.target := systemComplete.bits.nextPc
    if (p.fastHeadSystemRecovery) {
        // The only producer is a head-authorized, protected MachineSystemUnit.
        // Assertions prove its full identity; no dynamic 64-bit tag match is
        // inserted into the production valid/recovery/rename-acceptance path.
        headSystemRequest := systemComplete.valid && systemRedirect
        when(headSystemRequest) {
            assert(systemProtected && ledger.io.headValid && !systemComplete.bits.exception,
                "a trusted system redirect requires its irrevocable nonexception head transaction")
            assert(systemOwner.asUInt === ledger.io.headSystem.get.headToken.asUInt &&
                systemComplete.bits.token.asUInt === systemOwner.asUInt &&
                queue(head).renamed.token.asUInt === systemOwner.asUInt,
                "system completion, protected owner and current ROB/queue head must have the same full token")
            assert(!ledger.io.recoveryProbe.valid && !automaticTrap,
                "system protection excludes external recovery and automatic traps until precise completion/retirement")
        }
    } else {
        when(systemComplete.valid && systemRedirect) {
            branchCandidate.valid       := true.B
            branchCandidate.bits.token  := systemComplete.bits.token
            branchCandidate.bits.pc     := queue(systemComplete.bits.token.index).request.rename.pc
            branchCandidate.bits.target := systemComplete.bits.nextPc
        }
    }
    val localCandidate = Wire(Valid(new FrontendRedirect(p)))
    localCandidate := branchCandidate
    val replayValid = if (p.registeredLoadReplay) replayPendingValid.get else loadReplay.valid
    val replayIndex = if (p.registeredLoadReplay) replayPending.get.token.index else loadReplay.index
    val replayAge = if (p.registeredLoadReplay) replayIndex - head else loadReplay.age
    when(replayValid && (!branchCandidate.valid ||
        replayAge < (branchCandidate.bits.token.index - head))) {
        localCandidate.valid       := true.B
        localCandidate.bits.token  := (if (p.registeredLoadReplay) replayPending.get.token else
            loadReplayToken)
        localCandidate.bits.pc     := (if (p.registeredLoadReplay) replayPending.get.pc else
            loadReplayPc)
        localCandidate.bits.target := (if (p.registeredLoadReplay) replayPending.get.target else
            loadReplayPc)
        localInclusive             := true.B
    }
    earlyRecoveryIssueBlock := recovery.valid || headTrapRequest || headSystemRequest ||
        branchCandidate.valid || loadReplay.valid ||
        (if (p.registeredLoadReplay) replayPendingValid.get else false.B)
    ledger.io.parallelRecovery.foreach { port =>
        // A protected current-head system redirect supersedes all younger local
        // branches/replays, exactly as its former age-zero local candidate did.
        // Even during a repeated keep=1 rollback it must not expose a younger
        // candidate as an alternative authorization for completing the system op.
        port.local.valid := localCandidate.valid && !headSystemRequest
        port.local.bits.token := localCandidate.bits.token
        port.local.bits.inclusive := localInclusive
    }
    val externalWins = ledger.io.parallelRecovery.map(_.externalWins).getOrElse(
        ledger.io.recoveryProbeAccepted && (!localCandidate.valid ||
            (recovery.bits.token.index - head) <= (localCandidate.bits.token.index - head)))
    if (p.parallelRecoveryAdmission) {
        ledger.io.recover := ledger.io.parallelRecovery.get.selected
    } else {
        ledger.io.recover.valid          := externalWins || localCandidate.valid
        ledger.io.recover.bits.token     := Mux(externalWins, recovery.bits.token, localCandidate.bits.token)
        ledger.io.recover.bits.inclusive := Mux(externalWins, recovery.bits.inclusive, localInclusive)
    }
    io.recoveryAccepted              := headTrapAccepted || (externalWins && ledger.io.recoveryAccepted)
    val ordinaryLocalRedirectAccepted = !headTrapAccepted && !headSystemRequest && !externalWins &&
        localCandidate.valid && ledger.io.recoveryAccepted
    val localRedirectAccepted = headSystemAccepted || ordinaryLocalRedirectAccepted
    val localRedirect = Mux(headSystemAccepted, systemCandidate, localCandidate.bits)
    val trapRedirectAccepted = automaticTrap && (emptyTrap ||
        (if (p.fastHeadTrapRecovery) headTrapAccepted else io.recoveryAccepted))
    io.redirect.valid                := localRedirectAccepted
    io.redirect.bits                 := localRedirect
    when(trapRedirectAccepted) {
        io.redirect.valid       := true.B
        io.redirect.bits.token  := trapEvent.token
        io.redirect.bits.pc     := trapEvent.pc
        io.redirect.bits.target := trapTarget
    }
    val redirectTokens = if (p.parallelRedirectTokens) Some(Module(new RedirectTokenQualification(p))) else None
    redirectTokens.foreach { check =>
        check.io.local.valid := localRedirectAccepted
        check.io.local.bits := localRedirect.token
        check.io.trap.valid := trapRedirectAccepted
        check.io.trap.bits := trapEvent.token
        check.io.queries(0) := systemComplete.bits.token
        check.io.queries(1) := branchRedirect.token
    }
    val systemRedirectMatches = redirectTokens.map(_.io.matches(0)).getOrElse(
        io.redirect.valid && io.redirect.bits.token.asUInt === systemComplete.bits.token.asUInt)
    val branchRedirectMatches = redirectTokens.map(_.io.matches(1)).getOrElse(
        io.redirect.valid && io.redirect.bits.token.asUInt === branchRedirect.token.asUInt)
    io.invalidateFetch := systemInvalidate && systemRedirectMatches
    systemComplete.ready := !lsu.io.complete.valid && !mCompleteValid && ledger.io.completionAccepted(0)
    for (lane <- 0 until p.completionWidth) {
        val selectedBranch = selected(lane).valid &&
            queue(selected(lane).bits).request.controlFlow =/= ControlFlow.none
        val nonAluResult = if (lane == 0)
            lsu.io.complete.valid || mCompleteValid || systemComplete.valid else false.B
        val heldBranchResult = if (lane == 0) branchRedirectReady else false.B
        ledger.io.sameCycleRetire(lane) := nonAluResult || (!selectedBranch && !heldBranchResult)
    }
    // With two ALU slots and no direct-store issue, the memory/system/M unit can
    // consume at most slot 0. Keep the oldest ALU in lane 1 regardless of that
    // choice, and use lane 0 only for the second-oldest instruction when free.
    // This keeps LSU arbitration out of the branch operand/target path.
    val rankedIssue = p.registeredBranchRedirect && p.completionWidth == 2 && !p.fastBufferedStoreRetire
    val issueSelector = if (p.parallelIssuePayload)
        Some(Module(new CircularIssueSelector(p, parallelRanks = p.parallelIssueRanks,
            predecodedHead = p.registeredIssueHeadMask))) else None
    issueSelector.foreach { selector =>
        selector.io.head := head
        selector.io.headMask.foreach(_ := issueHeadMask.get)
        selector.io.eligible := VecInit((0 until p.robEntries).map(i =>
            eligible(i) && (!branchRedirectValid || queue(i).request.controlFlow === ControlFlow.none))).asUInt
    }
    val physicalOperands = if (p.oneHotPhysicalOperands) Some(independentPhysicalOperands()) else None
    physicalOperands.foreach { operands =>
        operands.io.owners(0) := issueSelector.get.io.second
        operands.io.owners(1) := issueSelector.get.io.first
        if (!p.lvtPhysicalRegisterFile) operands.io.values := values.get
        for (slot <- 0 until p.robEntries) {
            operands.io.source1(slot) := queue(slot).renamed.source1
            operands.io.source2(slot) := queue(slot).renamed.source2
        }
    }
    class EarlyStoreOperands extends Bundle {
        val token = new RobToken(p)
        val base = UInt(64.W)
        val immediate = UInt(64.W)
        val size = UInt(2.W)
        val data = UInt(64.W)
        val dataReady = Bool()
    }
    val earlyStorePayloads = if (p.sharedStoreOperandReads) {
        // Use common-ranked raw PRF operands before ALU forwarding. The same
        // preparation grants and one-cycle capture stage remain authoritative.
        val owners = Seq.fill(2)(Wire(UInt(p.robEntries.W)))
        val payloads = Wire(Vec(2, new EarlyStoreOperands))
        Some((owners, payloads))
    } else if (p.earlyStorePreparation) {
        val storeCandidates = Module(new StorePreparationEligibility(p))
        storeCandidates.io.head := head
        storeCandidates.io.branchRedirect := branchRedirectValid
        for (slot <- 0 until p.robEntries) {
            val entry = queue(slot)
            val candidate = storeCandidates.io.entries(slot)
            candidate.pending := pending(slot)
            candidate.system := false.B
            candidate.mulDiv := false.B
            candidate.memory := Mux(branchRedirectValid,
                storePreparationKinds.get(slot)(1), storePreparationKinds.get(slot)(0))
            candidate.store := true.B
            candidate.prepared := storePrepared(slot) || storePreparationBusy.get(slot)
            candidate.addressKnown := storeAddressKnown(slot)
            candidate.usePc := entry.request.usePc
            candidate.useImmediate := entry.request.useImmediate
            candidate.operandReady1 := ownerReady.map(_.io.ready1(slot)).getOrElse(
                operandReady(Mux(pending(slot), entry.renamed.source1, 0.U)))
            candidate.operandReady2 := ownerReady.map(_.io.ready2(slot)).getOrElse(
                operandReady(Mux(pending(slot), entry.renamed.source2, 0.U)))
            candidate.controlFlow := false.B // included in the registered redirect class
            // This is the exact store subset, not a wider speculative shortlist:
            // every common top-two store grant must appear in its own top two.
            // The old expression remains an assertion ONLY, never a payload input.
            assert(storeCandidates.io.eligible(slot) ===
                (eligible(slot) && entry.request.memory && entry.request.store &&
                    (!branchRedirectValid || entry.request.controlFlow === ControlFlow.none)),
                "early store eligibility must equal the original filtered issue set")
        }
        val stores = Module(new CircularIssueSelector(p, parallelRanks = true,
            predecodedHead = p.registeredIssueHeadMask))
        stores.io.head := head
        stores.io.headMask.foreach(_ := issueHeadMask.get)
        stores.io.eligible := storeCandidates.io.eligible
        val owners = Seq(stores.io.first, stores.io.second)
        val operands = independentPhysicalOperands()
        operands.io.owners := VecInit(owners)
        if (!p.lvtPhysicalRegisterFile) operands.io.values := values.get
        for (slot <- 0 until p.robEntries) {
            operands.io.source1(slot) := queue(slot).renamed.source1
            operands.io.source2(slot) := queue(slot).renamed.source2
        }
        val dataReady = VecInit((0 until p.robEntries).map(i =>
            ownerReady.map(_.io.ready2(i)).getOrElse(
                operandReady(Mux(pending(i), queue(i).renamed.source2, 0.U))))).asUInt
        val payloads = Wire(Vec(2, new EarlyStoreOperands))
        for (rank <- 0 until 2) {
            val entry = CircularIssueSelector.selectPayload(owners(rank), queue.map(_.asUInt).toSeq)
                .asTypeOf(new IntegerIssueEntry(p))
            payloads(rank).token := entry.renamed.token
            payloads(rank).base := operands.io.left(rank)
            payloads(rank).immediate := entry.request.immediate
            payloads(rank).size := entry.request.memorySize
            payloads(rank).data := operands.io.right(rank)
            payloads(rank).dataReady := (owners(rank) & dataReady).orR
        }
        Some((owners, payloads))
    } else None
    val rankedFirst = if (p.parallelIssuePayload) {
        val candidate = Wire(new Candidate)
        candidate.valid := issueSelector.get.io.firstValid
        candidate.index := issueSelector.get.io.firstIndex
        candidate.age := candidate.index - head
        candidate
    } else tournament((0 until p.robEntries).map { i =>
        val candidate = Wire(new Candidate)
        candidate.valid := eligible(i) && (!branchRedirectValid ||
            queue(i).request.controlFlow === ControlFlow.none)
        candidate.index := i.U
        candidate.age := ages(i)
        candidate
    })
    val rankedSecond = if (p.parallelIssuePayload) {
        val candidate = Wire(new Candidate)
        candidate.valid := issueSelector.get.io.secondValid
        candidate.index := issueSelector.get.io.secondIndex
        candidate.age := candidate.index - head
        candidate
    } else tournament((0 until p.robEntries).map { i =>
        val candidate = Wire(new Candidate)
        candidate.valid := eligible(i) && (!branchRedirectValid ||
            queue(i).request.controlFlow === ControlFlow.none) &&
            (!rankedFirst.valid || rankedFirst.index =/= i.U)
        candidate.index := i.U
        candidate.age := ages(i)
        candidate
    })
    for (lane <- 0 until p.completionWidth) {
        val usedIssues = PopCount(dispatched.take(lane).map(_.valid)) +& reserveSystem +&
            reserveMemory +& reserveMulDiv +& directStoreReserve
        val candidates = (0 until p.robEntries).map { i =>
            val candidate = Wire(new Candidate)
            val used      = (0 until lane)
                .map(j => dispatched(j).valid && dispatched(j).bits === i.U)
                .foldLeft(false.B)(_ || _)
            // The held redirect owns completion port 0. Lane 1 may still execute
            // non-control work; another branch waits until the redirect drains.
            val redirectAllowsLane = if (p.registeredBranchRedirect)
                !branchRedirectValid || ((lane > 0).B && queue(i).request.controlFlow === ControlFlow.none)
            else true.B
            candidate.valid := eligible(
                i
            ) && redirectAllowsLane &&
                !used && usedIssues < p.issueWidth.U && !(if (lane == 0)
                    lsu.io.complete.valid || mCompleteValid || systemComplete.valid ||
                        reserveSystem || reserveMemory || reserveMulDiv
                else false.B)
            candidate.index := i.U
            candidate.age   := ages(i)
            candidate
        }
        // Raw rank opportunity obeys the original two-issue/resource budget,
        // but is independent of execution-slot credit. Store preparation does
        // not consume an operand slot and must use this separate grant path.
        val issueOpportunity = Wire(Bool())
        val dispatchChoice = if (rankedIssue) {
            val rankedChoice = Wire(new Candidate)
            val executionCredit = if (p.registeredIssueExecute) {
                // Store address/data preparation consumes an issue grant but
                // never an execution slot. A held ALU must not block that
                // independent work solely because its operand slot is full.
                val preparationOnly = if (p.parallelIssuePayload) {
                    val owner = if (lane == 0) issueSelector.get.io.second else issueSelector.get.io.first
                    Mux1H((0 until p.robEntries).map(i =>
                        owner(i) -> (queue(i).request.memory && queue(i).request.store)))
                } else {
                    val rank = if (lane == 0) rankedSecond else rankedFirst
                    queue(rank.index).request.memory && queue(rank.index).request.store
                }
                executionStages(lane).io.enq.ready || preparationOnly
            } else true.B
            if (lane == 0) {
                rankedChoice := rankedSecond
                issueOpportunity := rankedSecond.valid && !branchRedirectValid &&
                    !(reserveSystem || reserveMemory || reserveMulDiv)
                rankedChoice.valid := issueOpportunity &&
                    (if (p.registeredIssueExecute) executionCredit
                        else !(lsu.io.complete.valid || mCompleteValid || systemComplete.valid))
            } else {
                rankedChoice := rankedFirst
                issueOpportunity := rankedFirst.valid
                rankedChoice.valid := issueOpportunity && executionCredit
            }
            rankedChoice
        } else {
            val ordinaryChoice = tournament(candidates)
            issueOpportunity := ordinaryChoice.valid
            ordinaryChoice
        }
        dispatched(lane).valid := dispatchChoice.valid
        dispatched(lane).bits  := dispatchChoice.index
        val dispatchEntry = if (p.parallelIssuePayload) {
            val oneHot = if (lane == 0) issueSelector.get.io.second else issueSelector.get.io.first
            CircularIssueSelector.selectPayload(oneHot, (0 until p.robEntries).map(i => queue(i).asUInt))
                .asTypeOf(new IntegerIssueEntry(p))
        } else queue(dispatchChoice.index)
        if (p.parallelIssuePayload) {
            when(dispatchChoice.valid) {
                assert(dispatchEntry.renamed.token.index === dispatchChoice.index,
                    "one-hot issue payload must belong to the selected live ROB owner")
            }
        }
        // Ranking fixes the payload index before slot-0 completion/reservation
        // arbitration. Compute operands even if that slot is subsequently denied;
        // every mutation/completion still uses the original late choice.valid.
        // Early validity retains the undefined-empty-payload guard for GSIM.
        val operandValid = if (p.earlyRankedOperands || p.registeredIssueExecute) {
            if (lane == 0) rankedSecond.valid else rankedFirst.valid
        } else dispatchChoice.valid
        // A zero one-hot selects an all-zero entry, including defined PRF IDs.
        // No grant-valid feedback is needed on payload IDs or the ownership token.
        val source1 = if (p.parallelIssuePayload) dispatchEntry.renamed.source1
            else Mux(operandValid, dispatchEntry.renamed.source1, 0.U)
        val source2 = if (p.parallelIssuePayload) dispatchEntry.renamed.source2
            else Mux(operandValid, dispatchEntry.renamed.source2, 0.U)
        val storedLeft = physicalOperands.map(_.io.left(lane)).getOrElse(operandValue(source1))
        val storedRight = physicalOperands.map(_.io.right(lane)).getOrElse(operandValue(source2))
        val dispatchLeft = Mux(dispatchEntry.request.memory, storedLeft, issueOperandValue(source1, storedLeft))
        val dispatchRight = Mux(dispatchEntry.request.memory, storedRight, issueOperandValue(source2, storedRight))
        if (p.sharedStoreOperandReads) {
            val (owners, payloads) = earlyStorePayloads.get
            val owner = if (lane == 0) issueSelector.get.io.second else issueSelector.get.io.first
            owners(lane) := owner
            payloads(lane).token := dispatchEntry.renamed.token
            payloads(lane).base := storedLeft
            payloads(lane).immediate := dispatchEntry.request.immediate
            payloads(lane).size := dispatchEntry.request.memorySize
            payloads(lane).data := storedRight
            val dataReady = VecInit((0 until p.robEntries).map(i => ownerReady.map(_.io.ready2(i)).getOrElse(
                operandReady(Mux(pending(i), queue(i).renamed.source2, 0.U))))).asUInt
            payloads(lane).dataReady := (owner & dataReady).orR
        }
        val dispatchStore = dispatchEntry.request.memory && dispatchEntry.request.store
        val preparationGrant = if (p.registeredIssueExecute) issueOpportunity else dispatchChoice.valid
        prepared(lane) := preparationGrant && dispatchStore && !killed(dispatchChoice.index) &&
            !ledger.io.headException.valid
        preparedOwners(lane) := Mux(prepared(lane), UIntToOH(dispatchChoice.index, p.robEntries), 0.U)
        if (!p.earlyStorePreparation) {
            when(prepared(lane)) {
                val preparedAddress = storedLeft + dispatchEntry.request.immediate
                // The selected issue entry can be undefined when choice.valid is false.
                // A lookup also avoids evaluating an out-of-range shift in the GSIM model.
                val preparedMask = MuxLookup(dispatchEntry.request.memorySize, 0.U(3.W))(
                    Seq(1.U -> 1.U(3.W), 2.U -> 3.U(3.W), 3.U -> 7.U(3.W)))
                val preparedAligned = (preparedAddress(2, 0) & preparedMask) === 0.U
                val preparedRam = SpeculativeRamRange.contains(p, preparedAddress, dispatchEntry.request.memorySize)
                storeAddressKnown(dispatchChoice.index) := true.B
                storeAddress(dispatchChoice.index) := preparedAddress
                storeByteLanes(dispatchChoice.index) :=
                    AlignedMemoryDisjoint.lanes(preparedAddress, dispatchEntry.request.memorySize)
                storeSafeRange(dispatchChoice.index) := preparedAligned && preparedRam
                when(operandReady(source2)) {
                    storePrepared(dispatchChoice.index) := true.B
                    storeData(dispatchChoice.index)     := storedRight
                }
            }
        }
        val choice = Wire(new Candidate)
        val entry = Wire(new IntegerIssueEntry(p))
        val leftValue = Wire(UInt(64.W))
        val rightValue = Wire(UInt(64.W))
        if (p.registeredIssueExecute) {
            val stage = executionStages(lane)
            val incoming = Wire(new IntegerExecutionOperands(p))
            incoming.entry := dispatchEntry
            incoming.left := dispatchLeft
            incoming.right := dispatchRight
            // Only legal metadata is used; tying operands to zero leaves no
            // duplicate arithmetic datapath after dead-code elimination. Share
            // the actual ALU's legality implementation instead of duplicating
            // its opcode/W-mode truth table in a scheduler-side decoder.
            val forwardLegality = Module(new IntegerAlu)
            forwardLegality.io.operation := dispatchEntry.request.operation
            forwardLegality.io.word := dispatchEntry.request.word
            forwardLegality.io.left := 0.U
            forwardLegality.io.right := 0.U
            incoming.forwardable := dispatchEntry.renamed.writesRd &&
                dispatchEntry.request.controlFlow === ControlFlow.none &&
                !dispatchEntry.request.fetchFault && !dispatchEntry.request.fetchPageFault && forwardLegality.io.legal
            stage.io.enq.valid := issueOpportunity && !dispatchStore &&
                !killed(dispatchChoice.index) && !ledger.io.pendingException.valid
            stage.io.enq.bits := incoming.asUInt
            io.loadIssueForwarded.foreach { witness =>
                val needsLeft = !dispatchEntry.request.usePc && loadIssueHit(source1)
                val needsRight = !dispatchEntry.request.useImmediate && loadIssueHit(source2)
                witness(lane) := Cat(stage.io.enq.fire && needsRight && !ready(source2),
                    stage.io.enq.fire && needsLeft && !ready(source1))
                when(stage.io.enq.fire && (needsLeft || needsRight)) {
                    assert(ledger.io.completionAccepted(0),
                        "captured load data requires accepted producer completion")
                    assert(!killed(Mux(loadIssueWake.valid, lsu.io.complete.bits.token.index, 0.U)),
                        "a surviving captured consumer cannot depend on a cancelled load producer")
                }
            }
            executionEnqueued(lane) := stage.io.enq.fire
            when(stage.io.enq.fire) { pending(dispatchChoice.index) := false.B }
            entry := executingOperands(lane).entry
            leftValue := executingOperands(lane).left
            rightValue := executingOperands(lane).right
            choice.valid := stage.io.deq.fire
            choice.index := entry.renamed.token.index
            choice.age := entry.renamed.token.index - head
            when(stage.io.deq.valid) {
                assert(!entry.request.memory && !entry.request.system && !entry.request.mulDiv,
                    "execution operand slots own only ordinary ALU and control-flow work")
            }
            // RAW producers precede their consumers, and recovery kills an
            // age suffix. Therefore a cancelled producer may affect ranking
            // speculatively, but no dependant may cross the authorized capture.
            for (producer <- executionStages.indices) {
                val cancelledPromise = executionWake(producer).valid && executionStages(producer).io.cancel
                val needsLeft = !dispatchEntry.request.usePc && source1 === executionWake(producer).bits
                val needsRight = !dispatchEntry.request.useImmediate && source2 === executionWake(producer).bits
                when(stage.io.enq.fire) {
                    assert(!(cancelledPromise && (needsLeft || needsRight)),
                        "a captured operand owner cannot depend on a same-cycle cancelled producer")
                }
            }
        } else {
            choice := dispatchChoice
            entry := dispatchEntry
            leftValue := dispatchLeft
            rightValue := dispatchRight
        }
        selected(lane).valid := choice.valid
        selected(lane).bits := choice.index
        val prepareStore = entry.request.memory && entry.request.store
        val alu = Module(new IntegerAlu(p.parallelAluResults, p.parallelAddressSums, p.parallelMinMaxResults, p.parallelMinMaxWordResults, p.parallelAluWordResults))
        alu.io.operation := entry.request.operation
        alu.io.word      := entry.request.word
        alu.io.left      := Mux(entry.request.usePc, entry.request.rename.pc, leftValue)
        alu.io.right     := Mux(entry.request.useImmediate, entry.request.immediate, rightValue)
        if (p.registeredIssueExecute) {
            // Availability uses early registered owner metadata and physical
            // writeback availability. Do NOT use deq.fire: its late cancel
            // would reconnect recovery -> wake -> rank -> PRF -> store address.
            // Actual completion and all next-owner captures retain current kill.
            val stage = executionStages(lane)
            executionWake(lane).valid := stage.io.occupied && stage.io.deq.ready &&
                executingOperands(lane).forwardable
            executionWake(lane).bits := entry.renamed.destination
            executionData(lane) := alu.io.result
            when(stage.io.occupied) {
                assert(executingOperands(lane).forwardable === (entry.renamed.writesRd &&
                    entry.request.controlFlow === ControlFlow.none && !entry.request.fetchFault &&
                    !entry.request.fetchPageFault && alu.io.legal),
                    "registered forwarding permission must match the executing ALU owner")
            }
        }
        val branch = Module(new BranchUnit(p.compressedInstructions, p.balancedBranchCompare))
        val shortInstruction = p.compressedInstructions.B &&
            entry.request.rename.instruction(1, 0) =/= 3.U
        val nextSequential = entry.request.rename.pc + Mux(shortInstruction, 2.U, 4.U)
        branch.io.kind      := entry.request.controlFlow
        branch.io.pc        := entry.request.rename.pc
        branch.io.shortInstruction := shortInstruction
        branch.io.immediate := entry.request.immediate
        branch.io.left      := leftValue
        branch.io.right     := rightValue
        val isControl  = entry.request.controlFlow =/= ControlFlow.none
        val legal      = Mux(isControl, branch.io.legal, alu.io.legal)
        val misaligned = isControl && branch.io.misaligned
        completion(lane).token := (if (p.parallelIssuePayload) entry.renamed.token
            else Mux(choice.valid, entry.renamed.token, 0.U.asTypeOf(new RobToken(p))))
        completion(lane).data      := Mux(isControl, branch.io.data, alu.io.result)
        completion(lane).nextPc    := Mux(isControl, branch.io.nextPc, nextSequential)
        completion(lane).exception := entry.request.fetchFault || entry.request.fetchPageFault || !legal || misaligned
        // Control-flow completions are already barred from same-cycle retirement.
        // Do not put their taken/alignment comparison on the non-control bypass.
        // Preserve the full exception for ROB state, PRF wake/data and trap logic.
        val retireFault = WireDefault(entry.request.fetchFault || entry.request.fetchPageFault || !legal)
        ledger.io.sameCycleFault.foreach(_(lane) := retireFault)
        completion(lane).cause     := Mux(entry.request.fetchPageFault, MCause.InstrPageFault,
            Mux(entry.request.fetchFault, MCause.InstrAccessFault,
                Mux(!legal, MCause.IllegalInstr, MCause.InstrAddrMisaligned)))
        completion(lane).tval      := Mux(entry.request.fetchFault || entry.request.fetchPageFault,
            entry.request.fetchTval,
            Mux(!legal, entry.request.rename.instruction, branch.io.target))
        newResolutions(lane).valid := choice.valid && isControl && legal && !misaligned &&
            branch.io.nextPc =/= Mux(
                entry.request.predictedNextPc.valid,
                entry.request.predictedNextPc.bits,
                nextSequential
            )
        newResolutions(lane).bits.token  := entry.renamed.token
        newResolutions(lane).bits.pc     := entry.request.rename.pc
        newResolutions(lane).bits.target := branch.io.nextPc
        // The optional precompletion mode writes the mispredicted branch into the ROB now,
        // but registered retirement and branchRetirementHold keep it architectural only
        // after the redirect. The ordinary registered mode waits to complete it instead.
        ledger.io.complete(lane).valid := (if (p.precompleteMispredictedBranch)
            choice.valid && !prepareStore
        else if (p.registeredBranchRedirect)
            choice.valid && !prepareStore && !newResolutions(lane).valid
        else choice.valid && !prepareStore && (!newResolutions(lane).valid ||
            (io.redirect.valid && io.redirect.bits.token.asUInt === entry.renamed.token.asUInt)))
        ledger.io.complete(lane).bits := completion(lane)
        if (lane == 0) {
            if (p.registeredBranchRedirect && !p.precompleteMispredictedBranch) {
                when(branchRedirectReady) {
                    ledger.io.complete(lane).valid :=
                        branchRedirectMatches
                    if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := branchResult }
                    retireFault := branchResult.exception
                }
            }
            when(systemComplete.valid) {
                ledger.io.complete(lane).valid := !systemRedirect || systemRedirectMatches
                if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := systemComplete.bits }
                retireFault := systemComplete.bits.exception
            }
            when(multiplier.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := multiplier.io.complete.bits }
                retireFault := multiplier.io.complete.bits.exception
            }
            when(mulDiv.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := mulDiv.io.complete.bits }
                retireFault := mulDiv.io.complete.bits.exception
            }
            when(lsu.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := lsu.io.complete.bits }
                retireFault := lsu.io.complete.bits.exception
            }
            if (p.parallelCompletionPayload) {
                val payload = Module(new ParallelCompletionPayload(p))
                val heldBranchPresent = if (p.registeredBranchRedirect && !p.precompleteMispredictedBranch)
                    branchRedirectReady else false.B
                payload.io.present := VecInit(Seq(lsu.io.complete.valid, mulDiv.io.complete.valid,
                    multiplier.io.complete.valid, systemComplete.valid, heldBranchPresent)).asUInt
                payload.io.candidates := VecInit(Seq(lsu.io.complete.bits, mulDiv.io.complete.bits,
                    multiplier.io.complete.bits, systemComplete.bits, branchResult))
                payload.io.fallback := completion(lane)
                ledger.io.complete(lane).bits := payload.io.selected
            }
        }
        io.issued(lane)       := ledger.io.complete(lane)
        io.issued(lane).valid := ledger.io.completionAccepted(lane)
        if (p.registeredIssueExecute) {
            when(executionStages(lane).io.deq.fire) {
                assert(ledger.io.completionAccepted(lane),
                    "a live execution operand owner may drain only into an accepted ROB completion")
            }
        }
        val completedIndex = ledger.io.complete(lane).bits.token.index
        val completedEntry = queue(completedIndex)
        when(ledger.io.completionAccepted(lane)) { pending(completedIndex) := false.B }
        when(
            ledger.io
                .completionAccepted(lane) && !ledger.io.complete(lane).bits.exception && completedEntry.renamed.writesRd
        ) {
            if (p.lvtPhysicalRegisterFile) {
                physicalWrites.get(lane).valid := true.B
                physicalWrites.get(lane).bits.address := completedEntry.renamed.destination
                physicalWrites.get(lane).bits.data := ledger.io.complete(lane).bits.data
            } else values.get(completedEntry.renamed.destination) := ledger.io.complete(lane).bits.data
            if (!p.parallelPrfReadyUpdates) { ready(completedEntry.renamed.destination) := true.B }
        }
        readyUpdate.foreach { update =>
            update.io.wake(lane).valid := ledger.io.completionAccepted(lane) &&
                !ledger.io.complete(lane).bits.exception && completedEntry.renamed.writesRd
            update.io.wake(lane).bits := completedEntry.renamed.destination
        }
    }
    earlyStorePayloads.foreach { case (owners, payloads) =>
        // A store among the shared oldest two is necessarily among the store-
        // only oldest two. Keep its original shared issue budget/kill grant,
        // but capture complete operands BEFORE AGU/end arithmetic.
        // No ALU early-wakeup or execution-slot credit can choose this payload.
        val grants = preparedOwners.reduce(_ | _)
        assert((grants & ~(owners(0) | owners(1))) === 0.U,
            "every granted store must be covered by an independent early store payload")
        // Two granted owners/cycle, fixed one-cycle preparation latency, II=1.
        // The reservation mask excludes duplicate preparation while the stage
        // computes the address. No data/owner is resampled after authorization.
        val captured = Reg(Vec(2, new EarlyStoreOperands))
        val capturedOwners = RegInit(VecInit(Seq.fill(2)(0.U(p.robEntries.W))))
        storePreparationBusy.get := grants
        for (rank <- 0 until 2) {
            captured(rank) := payloads(rank)
            capturedOwners(rank) := owners(rank) & grants
        }
        val preparedAddresses = (0 until 2).map(rank => captured(rank).base + captured(rank).immediate)
        val preparedLanes = (0 until 2).map(rank =>
            AlignedMemoryDisjoint.lanes(preparedAddresses(rank), captured(rank).size))
        val preparedSafeRanges = (0 until 2).map { rank =>
            val mask = MuxLookup(captured(rank).size, 0.U(3.W))(
                Seq(1.U -> 1.U(3.W), 2.U -> 3.U(3.W), 3.U -> 7.U(3.W)))
            (preparedAddresses(rank)(2, 0) & mask) === 0.U &&
                SpeculativeRamRange.contains(p, preparedAddresses(rank), captured(rank).size)
        }
        for (slot <- 0 until p.robEntries; rank <- 0 until 2) {
            when(grants(slot) && owners(rank)(slot)) {
                assert(payloads(rank).token.asUInt === queue(slot).renamed.token.asUInt,
                    "early store payload must match the final granted owner token")
            }
            val operand = captured(rank)
            val liveOwner = pending(slot) && memoryLive(slot) && !killed(slot) &&
                queue(slot).renamed.token.asUInt === operand.token.asUInt
            when(capturedOwners(rank)(slot) && liveOwner) {
                storeAddressKnown(slot) := true.B
                storeAddress(slot) := preparedAddresses(rank)
                storeByteLanes(slot) := preparedLanes(rank)
                storeSafeRange(slot) := preparedSafeRanges(rank)
                when(operand.dataReady) {
                    storePrepared(slot) := true.B
                    storeData(slot) := operand.data
                }
            }
        }
    }
    if (p.registeredBranchRedirect) {
        assert(!io.recover.valid, "registered branch redirects require no external recovery producer")
        // Elastic execution lanes may hold owners from DIFFERENT dispatch
        // cycles. Rank actual registered owners, not the old lane-1-is-oldest
        // convention. Qualify the chosen winner only afterwards: killing the
        // older winner must never fall back to a younger redirect.
        val resolutionWinners = if (p.registeredIssueExecute) {
            VecInit((0 until p.completionWidth).map { lane =>
                newResolutions(lane).valid && (0 until p.completionWidth).filter(_ != lane).map { other =>
                    !newResolutions(other).valid ||
                        (selected(lane).bits - head) < (selected(other).bits - head)
                }.reduce(_ && _)
            }).asUInt
        } else VecInit(newResolutions.map(_.valid)).asUInt
        if (p.earlyRedirectCapture) {
            val capture = Module(new EarlyRedirectCapture(p, oldestHighLane = rankedIssue))
            capture.io.flags := resolutionWinners
            capture.io.killed := killed.asUInt
            capture.io.blocked := branchRedirectValid
            for (lane <- 0 until p.completionWidth) {
                capture.io.indices(lane) := selected(lane).bits
                when(newResolutions(lane).valid) {
                    assert(newResolutions(lane).bits.token.index === selected(lane).bits,
                        "early redirect index must belong to the resolved instruction")
                }
            }
            when(capture.io.accept) {
                branchRedirectValid := true.B
                branchRedirect := Mux1H((0 until p.completionWidth).map(lane =>
                    capture.io.selected(lane) -> newResolutions(lane).bits))
                branchResult := Mux1H((0 until p.completionWidth).map(lane =>
                    capture.io.selected(lane) -> completion(lane)))
            }
            for (slot <- 0 until p.robEntries) {
                when(capture.io.clear(slot)) { pending(slot) := false.B }
            }
        } else {
            val captureFlags = (0 until p.completionWidth).map(resolutionWinners(_))
            val captureBranch = captureFlags.reduce(_ || _)
            val captureOrder = if (rankedIssue) captureFlags.zip(newResolutions).zip(completion).reverse.toSeq
                else captureFlags.zip(newResolutions).zip(completion).toSeq
            val captureRedirect = PriorityMux(captureOrder.map { case ((flag, r), _) => flag -> r.bits })
            val captureResult = PriorityMux(captureOrder.map { case ((flag, _), c) => flag -> c })
            val captureIndex = Mux(captureBranch, captureRedirect.token.index, 0.U)
            when(captureBranch && !branchRedirectValid && !killed(captureIndex)) {
                branchRedirectValid := true.B
                branchRedirect      := captureRedirect
                branchResult        := captureResult
                pending(captureIndex) := false.B
            }
        }
        // The inactive redirect payload is unspecified. Guard the index itself,
        // not only the enclosing Boolean, for safe combinational evaluation.
        when(branchRedirectValid &&
            (branchRedirectMatches ||
                killed(Mux(branchRedirectValid, branchRedirect.token.index, 0.U)))) {
            branchRedirectValid := false.B
        }
    }
    when(fastLoadRetire && headRenamed.writesRd) {
        if (!p.lvtPhysicalRegisterFile) values.get(headRenamed.destination) := lsu.io.fastLoadPreview.bits.data
        if (!p.parallelPrfReadyUpdates) { ready(headRenamed.destination) := true.B }
    }
    readyUpdate.foreach { update =>
        update.io.wake(p.completionWidth).valid := fastLoadRetire && headRenamed.writesRd
        update.io.wake(p.completionWidth).bits := headRenamed.destination
    }
    val aluIssues = (0 until p.completionWidth).map(lane =>
        ledger.io.completionAccepted(lane) &&
            !(if (lane == 0) lsu.io.complete.valid || mCompleteValid || systemComplete.valid else false.B)
    )
    io.mulDivOverlap := (mulDiv.io.busy || multiplier.io.busy) && aluIssues.reduce(_ || _)
    io.issueCount    := (if (p.registeredIssueExecute) PopCount(executionEnqueued) else PopCount(aluIssues)) + PopCount(
        prepared
    ) + systemStart + lsu.io.start.fire + mulDiv.io.start.fire + multiplier.io.start.fire +
        directStoreFire
    assert(PopCount(dispatched.map(_.valid)) +& reserveSystem +& reserveMemory +& reserveMulDiv +&
        directStoreReserve <= p.issueWidth.U)
    // Allocation takes priority over ready writes. Same-packet RAW reads the newly allocated, unready ID.
    for (lane <- 0 until p.renameWidth) {
        val renamed = ledger.io.renamed(lane)
        when(renamed.valid) {
            queue(renamed.bits.token.index).renamed := renamed.bits
            queue(renamed.bits.token.index).request := io.allocate(lane).bits
            storePreparationKinds.foreach { kinds =>
                val offered = io.allocate(lane).bits
                val storeClass = !offered.system && !offered.mulDiv && offered.memory && offered.store
                kinds(renamed.bits.token.index) := Cat(
                    storeClass && offered.controlFlow === ControlFlow.none, storeClass)
            }
            pending(renamed.bits.token.index)       := true.B
            memoryLive(renamed.bits.token.index)    := io.allocate(lane).bits.memory
            memoryCanonical.foreach(_(renamed.bits.token.index) := false.B)
            storeAddressKnown(renamed.bits.token.index) := false.B
            storePrepared(renamed.bits.token.index) := false.B
            when(renamed.bits.writesRd && !renamed.bits.moveAlias) {
                if (!p.parallelPrfReadyUpdates) { ready(renamed.bits.destination) := false.B }
            }
        }
        readyUpdate.foreach { update =>
            update.io.reserve(lane).valid := renamed.valid && renamed.bits.writesRd && !renamed.bits.moveAlias
            update.io.reserve(lane).bits := renamed.bits.destination
        }
    }
    if (p.lvtPhysicalRegisterFile) {
        val physicalFile = Module(new OwnerBankedPhysicalRegisterFile(p.physicalRegs, physicalReads.length))
        physicalFile.io.write := physicalWrites.get
        for (((address, data), port) <- physicalReads.zipWithIndex) {
            physicalFile.io.address(port) := address
            data := physicalFile.io.data(port)
        }
    }

}
