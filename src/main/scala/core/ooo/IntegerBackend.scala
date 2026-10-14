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
class IntegerBackend(val p: OooParams = OooParams(), canonicalHandoff: Boolean = false,
    val registerCanonicalStoreEvent: Boolean = false, val retirementSlotIdentity: Boolean = false) extends Module {
    require(retirementSlotIdentity == p.retirementSlotIdentity,
        "backend retirement-slot identity must use its unified OooParams flag")
    // Read-only view of the single profile option; no separate constructor switch.
    val shareCanonicalStoreOwnerMatch = p.sharedCanonicalStoreOwnerMatch
    require(registerCanonicalStoreEvent == p.registeredCanonicalStoreEvent,
        "canonical event producer and backend lifecycle must use the same OooParams flag")
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
        val pmpRawChanged = if (p.pmpChangePublicationEnabled) Some(Output(Bool())) else None
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
        val memory                      = new DataPort(p.dataReturnHandleBits)
        val loadPrecheck = if (p.virtualRamLoadPrecheck) Some(new VirtualLoadPrecheckPort) else None
        val posted = p.postedProofConfig.map(c => new PostedStoreCpuPort(c))
        val canonicalStore = if (p.canonicalVirtualStoreOverlap) Some(new CanonicalStoreCpuPort(p)) else None
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
    val ledger          = Module(new RenameRob(p, retirementSlotIdentity = retirementSlotIdentity))
    ledger.io.rawDestinations.foreach(_ := io.rawDestinations.get)
    ledger.io.rawRequests.foreach(_ := io.rawRequests.get)
    ledger.io.fetchFaultMask.foreach(_ := io.fetchFaultMask.get)
    val lsu             = Module(new ParallelLoadStoreUnit(p, canonicalHandoff,
        localTaggedResponseReady = p.localTaggedResponseReady))
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
    val integerMemory = Wire(new DataPort(p.dataReturnHandleBits))
    val integerMemoryBusy = WireDefault(lsu.io.busy)
    val postedCompleted = WireDefault(false.B)
    val postedStarted = WireDefault(false.B)
    val postedCount = if (p.postedStoreMerge) Some(RegInit(0.U(log2Ceil(p.storeBufferEntries + p.memoryEntries + 2).W))) else None
    val externalPostedBusy = io.posted.map(_.externalBusy).getOrElse(false.B)
    val postedBusy = postedCount.map(_ =/= 0.U).getOrElse(false.B) || externalPostedBusy
    val blockPostedStart = io.posted.map(_.blockNew).getOrElse(false.B)
    val integerProof = p.postedProofConfig.map(c => Wire(Valid(new PostedStoreProof(c))))
    val fastProof = p.postedProofConfig.map(c => Wire(Valid(new PostedStoreProof(c))))
    val integerCanonicalOrigin = if (p.canonicalVirtualStoreOverlap)
        Some(Wire(Valid(new CanonicalStoreOrigin(p)))) else None
    val integerFrozenProof = if (p.frozenStoreProofEnabled) Some(Wire(Valid(new FrozenStoreProof))) else None
    // Accepted CPU ownership only; PF stays in memoryBusy for every strong boundary.
    // Elaboration-OFF creates no new hardware. Never derive this from start/ready/aggregateDrained.
    val cpuAcceptedMemoryBusy = if (p.postedPrefetchHeadOffer)
        Some(WireDefault(integerMemoryBusy || postedBusy)) else None
    io.memoryBusy      := integerMemoryBusy || postedBusy || io.externalPrefetchBusy.getOrElse(false.B)
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
            val requests = Module(new Queue(new DataRequest(p.dataReturnHandleBits), p.memoryEntries, pipe = false, flow = false))
            observationRequests = Some(requests)
            requests.io.enq <> lsu.io.memory.request
            p.postedProofConfig.foreach { c =>
                val proofQueue = Module(new Queue(Valid(new PostedStoreProof(c)), p.memoryEntries, pipe = false, flow = false))
                proofQueue.io.enq.valid := requests.io.enq.fire
                proofQueue.io.enq.bits := lsu.io.postedProof.get
                proofQueue.io.deq.ready := requests.io.deq.fire
                stores.io.upstreamProof.get := proofQueue.io.deq.bits
                stores.io.upstreamProof.get.valid := requests.io.deq.valid && proofQueue.io.deq.bits.valid
                assert(proofQueue.io.deq.valid === requests.io.deq.valid, "request FIFO and proof capture share every transfer")
                when(requests.io.enq.fire) { assert(proofQueue.io.enq.ready) }
            }
            if (p.canonicalVirtualStoreOverlap) {
                val origins = Module(new Queue(Valid(new CanonicalStoreOrigin(p)), p.memoryEntries,
                    pipe = false, flow = false))
                origins.io.enq.valid := requests.io.enq.fire
                origins.io.enq.bits := lsu.io.canonicalStoreOrigin.get
                origins.io.deq.ready := requests.io.deq.fire
                stores.io.upstreamCanonicalStoreOrigin.get := origins.io.deq.bits
                stores.io.upstreamCanonicalStoreOrigin.get.valid := requests.io.deq.valid && origins.io.deq.bits.valid
                assert(origins.io.deq.valid === requests.io.deq.valid,
                    "canonical origin FIFO shares every registered request transfer")
                when(requests.io.enq.fire) { assert(origins.io.enq.ready) }
            }
            if (p.frozenStoreProofEnabled) {
                val frozen = Module(new Queue(Valid(new FrozenStoreProof), p.memoryEntries, pipe = false, flow = false))
                frozen.io.enq.valid := requests.io.enq.fire
                frozen.io.enq.bits := lsu.io.frozenStoreProof.get
                frozen.io.deq.ready := requests.io.deq.fire
                stores.io.upstreamFrozenStoreProof.get := frozen.io.deq.bits
                stores.io.upstreamFrozenStoreProof.get.valid := requests.io.deq.valid && frozen.io.deq.bits.valid
                assert(frozen.io.deq.valid === requests.io.deq.valid,
                    "frozen store tuple shares every original DataRequest transfer")
                when(requests.io.enq.fire) { assert(frozen.io.enq.ready) }
            }
            stores.io.upstream.request <> requests.io.deq
            // Queue storage is undefined while empty. Keep only the size/shift
            // operand defined, using registered queue validity (not late issue).
            stores.io.upstream.request.bits.size := Mux(requests.io.deq.valid, requests.io.deq.bits.size, 0.U)
            stores.io.upstream.response <> lsu.io.memory.response
        } else {
            stores.io.upstream <> lsu.io.memory
            stores.io.upstreamProof.foreach(_ := lsu.io.postedProof.get)
            stores.io.upstreamCanonicalStoreOrigin.foreach(_ := lsu.io.canonicalStoreOrigin.get)
            stores.io.upstreamFrozenStoreProof.foreach(_ := lsu.io.frozenStoreProof.get)
        }
        stores.io.fastStore.valid := fastStoreValid
        stores.io.fastStore.bits := fastStoreRequest
        fastStoreReady := stores.io.fastStore.ready
        stores.io.fastProof.foreach(_ := fastProof.get)
        stores.io.externalPostedBusy.foreach(_ := externalPostedBusy)
        integerProof.foreach(_ := stores.io.memoryProof.get)
        integerCanonicalOrigin.foreach(_ := stores.io.memoryCanonicalStoreOrigin.get)
        integerFrozenProof.foreach(_ := stores.io.memoryFrozenStoreProof.get)
        postedCompleted := stores.io.postedCompleted.map(_.valid).getOrElse(false.B)
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
        CpuReturnTransport.requestPayload(io.memory.request.bits,
            Mux(fpMemoryEpoch, fpMemory.request.bits, {
                val payload = Wire(new DataRequest)
                CpuReturnTransport.requestPayload(payload, integerMemory.request.bits)
                payload
            }))
        io.memory.request.bits.returnHandle.foreach(_ := Mux(fpMemoryEpoch,
            p.cpuReturnConfig.get.fpHandle.U, integerMemory.request.bits.returnHandle.get))
        fpMemory.request.ready := fpMemoryEpoch && io.memory.request.ready
        integerMemory.request.ready := !fpMemoryEpoch && io.memory.request.ready
        fpMemory.response.valid := fpMemoryEpoch && io.memory.response.valid
        CpuReturnTransport.responsePayload(fpMemory.response.bits, io.memory.response.bits)
        integerMemory.response.valid := !fpMemoryEpoch && io.memory.response.valid
        integerMemory.response.bits := io.memory.response.bits
        io.memory.response.ready := Mux(fpMemoryEpoch, fpMemory.response.ready, integerMemory.response.ready)
        io.memoryBusy := integerMemoryBusy || systemUnit.get.io.fpMemoryBusy.get || postedBusy || io.externalPrefetchBusy.getOrElse(false.B)
        cpuAcceptedMemoryBusy.foreach(_ := integerMemoryBusy || systemUnit.get.io.fpMemoryBusy.get || postedBusy)
        when(fpMemoryEpoch) { assert(!integerMemoryBusy, "integer memory drained before FP ownership") }
        p.cpuReturnConfig.foreach { config =>
            when(fpMemoryEpoch && io.memory.response.valid) {
                assert(io.memory.response.bits.returnHandle.get === config.fpHandle.U,
                    "exclusive FP response lost its drained domain")
            }
        }
    } else {
        io.memory <> integerMemory
    }
    io.canonicalStore.foreach { canonical =>
        canonical.requestOrigin := integerCanonicalOrigin.get
        canonical.requestOrigin.valid := io.memory.request.valid && !fpMemoryEpoch && integerCanonicalOrigin.get.valid
        canonical.requestFrozenProof.foreach { frozen =>
            frozen := integerFrozenProof.get
            frozen.valid := io.memory.request.valid && !fpMemoryEpoch && integerFrozenProof.get.valid
        }
        CanonicalVirtualStore.held(io.memory.request, canonical.requestOrigin)
    }
    io.posted.foreach { posted =>
        posted.requestProof := integerProof.get
        posted.requestProof.valid := io.memory.request.valid && !fpMemoryEpoch && integerProof.get.valid
        posted.busy := postedCount.get =/= 0.U
        posted.starting := postedStarted
        when(postedStarted =/= postedCompleted) {
            postedCount.get := Mux(postedStarted, postedCount.get + 1.U, postedCount.get - 1.U)
        }
        when(postedCompleted) { assert(postedCount.get =/= 0.U || postedStarted) }
        assert(postedCount.get <= (p.storeBufferEntries + p.memoryEntries).U)
        PostedStoreCpu.held(io.memory.request, posted.requestProof)
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
    // A row has one immutable operation class for its live ROB generation.
    // Stores retain their full prepared VA; ordinary loads retain only the
    // canonical beat and byte lanes consumed by replay. All existing validity,
    // token and canonical-address checks continue to select the interpretation.
    val loadBeat = if (p.sharedMemoryAddressState) VecInit(storeAddress.map(_(63, 3)))
        else Reg(Vec(p.robEntries, UInt(61.W)))
    val loadLanes = if (p.sharedMemoryAddressState) storeByteLanes
        else Reg(Vec(p.robEntries, UInt(8.W)))
    // These combinational witnesses are used only by assertions, not arbitration.
    val sharedAddressLoadWrite = if (p.sharedMemoryAddressState)
        Some(lsu.io.start.fire && !lsu.io.start.bits.store && !lsu.io.start.bits.atomic) else None
    val sharedAddressStoreWrites = if (p.sharedMemoryAddressState)
        Some(Wire(Vec(p.robEntries, Vec(p.completionWidth, Bool())))) else None
    sharedAddressStoreWrites.foreach(writes => writes := 0.U.asTypeOf(writes))
    val orderCheckValid = RegInit(false.B)
    val orderCheckIndex = RegInit(0.U(p.robBits.W))
    val orderCheckTag = if (p.loadOrderOlderRetire) Some(RegInit(0.U(p.tagBits.W))) else None
    val orderCheckBeat  = Reg(UInt(61.W))
    val orderCheckLanes = Reg(UInt(8.W))
    val replayPendingValid = if (p.registeredLoadReplay) Some(RegInit(false.B)) else None
    val replayPending = if (p.registeredLoadReplay) Some(Reg(new FrontendRedirect(p))) else None
    ledger.io.loadOrderRetireLimit.foreach { limit =>
        limit.valid := orderCheckValid
        limit.bits.index := orderCheckIndex
        limit.bits.tag := orderCheckTag.get
    }
    val queue         = Reg(Vec(p.robEntries, new IntegerIssueEntry(p)))
    // Stale rows need no clear: the unchanged pending/system head gate owns
    // validity, and accepted allocation overwrites the bit with its payload.
    val headDrainClasses = if (p.predecodedHeadDrain) Some(Reg(Vec(p.robEntries, Bool()))) else None
    // Allocation is the only queue writer and targets renamed.token.index. Rows
    // never move: a live row's index is its slot for its entire generation. Keep
    // the full tag in storage and reconstruct only that fixed index BEFORE every
    // dynamic/one-hot read. Captured producer tokens and all owner checks stay full.
    // OFF is a Scala alias, so the original register names and circuitry remain.
    val issueEntries = if (p.reconstructIssueTokenIndex) {
        val entries = WireDefault(queue)
        for (slot <- 0 until p.robEntries) {
            entries(slot).renamed.token.index := slot.U(p.robBits.W)
        }
        entries
    } else queue
    // In the RAM profile, the six large immutable fields in this register view
    // are tied to zero at allocation and optimized away. Full token/source/class
    // metadata remains local to the scheduler and all completion owner checks.
    // Only explicit selected consumers below may request a payload memory port.
    val issuePayloadReads = scala.collection.mutable.ArrayBuffer.empty[
        (String, UInt, Bool, Set[String], ImmutableIssuePayload)]
    def readIssue(index: UInt, name: String, fields: Set[String] = ImmutableIssuePayload.all,
        owner: Option[UInt] = None): IntegerIssueEntry = {
        val metadata = owner.map(mask => CircularIssueSelector.selectPayload(mask, issueEntries.map(_.asUInt).toSeq)
            .asTypeOf(new IntegerIssueEntry(p))).getOrElse(issueEntries(index))
        if (!p.bankedIssuePayload) metadata
        else {
            val payload = Wire(new ImmutableIssuePayload).suggestName(s"${name}Payload")
            issuePayloadReads += ((name, index, owner.map(_.orR).getOrElse(true.B), fields, payload))
            val entry = Wire(new IntegerIssueEntry(p)).suggestName(s"${name}Entry")
            entry := metadata
            ImmutableIssuePayload.insert(entry.request, payload)
            entry
        }
    }
    val queuedSourceDecode = if (p.sharedPhysicalSourceDecode && !p.lvtPhysicalRegisterFile)
        Some(Module(new QueuedPhysicalSourceDecode(p))) else None
    queuedSourceDecode.foreach { decode =>
        for (slot <- 0 until p.robEntries) {
            decode.io.source1(slot) := issueEntries(slot).renamed.source1
            decode.io.source2(slot) := issueEntries(slot).renamed.source2
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
    def executionReadyClass(request: IntegerRequest): Bool = !request.memory && !request.mulDiv && !request.system
    val heldLoadDestinations = if (p.registeredLoadResultReady) Some(Wire(Vec(p.memoryEntries,
        Valid(UInt(p.physBits.W))))) else None
    heldLoadDestinations.foreach { destinations =>
        for (slot <- 0 until p.memoryEntries) {
            destinations(slot).valid := lsu.io.heldLoadValue.get(slot).valid
            destinations(slot).bits := lsu.io.heldLoadValue.get(slot).bits.destination
        }
    }
    val ownerReady = if (p.ownerLocalOperandReady)
        Some(Module(new OwnerOperandReady(p, precomputedAllocationReady = p.tentativeRenameSources))) else None
    ownerReady.foreach { mirror =>
        mirror.io.physical := ready.asUInt
        mirror.io.active := pending.asUInt
        mirror.io.wake := readyUpdate.get.io.wake
        mirror.io.reserve := readyUpdate.get.io.reserve
        if (p.registeredLoadResultReady) {
            mirror.io.executionClass.get := VecInit(issueEntries.map(e => executionReadyClass(e.request)))
            mirror.io.allocationExecutionClass.get := VecInit(io.allocate.map(a => executionReadyClass(a.bits)))
            mirror.io.heldLoads.get := heldLoadDestinations.get
            mirror.io.publishedLoads.get := lsu.io.loadResultPublish.get
        }
        if (p.tentativeRenameSources) {
            // These candidate ID reads start before PMP/fault selection. Keep
            // the original accepted wake/reserve events, then select Booleans.
            val initialization = Module(new FaultAwareAllocationReady(p))
            initialization.io.sources := ledger.io.sourceCandidates.get
            initialization.io.faults := io.fetchFaultMask.get
            initialization.io.physical := ready.asUInt
            initialization.io.wake := readyUpdate.get.io.wake
            initialization.io.reserve := readyUpdate.get.io.reserve
            if (p.registeredLoadResultReady) {
                initialization.io.allocationExecutionClass.get := mirror.io.allocationExecutionClass.get
                initialization.io.heldLoads.get := heldLoadDestinations.get
                initialization.io.publishedLoads.get := lsu.io.loadResultPublish.get
            }
            mirror.io.allocationReady1.get := initialization.io.ready1
            mirror.io.allocationReady2.get := initialization.io.ready2
        }
        for (slot <- 0 until p.robEntries) {
            mirror.io.source1(slot) := issueEntries(slot).renamed.source1
            mirror.io.source2(slot) := issueEntries(slot).renamed.source2
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
    val memoryPreparationHeadOwner = if (p.memoryPreparationHeadMask)
        Some(MemoryPreparationLocality.headOwner(issueHeadMask.get)) else None
    val memoryPreparationDirectSourceRanks = Seq(p.directRank0MemorySourceIds, p.directRank1MemorySourceIds)
    def memoryPreparationAtHead(slot: Int): Bool =
        memoryPreparationHeadOwner.map(_(slot)).getOrElse(slot.U === head)
    val headRequest = readIssue(head, "head", ImmutableIssuePayload.head).request
    val headRenamed = issueEntries(head).renamed
    // A completed load has its result in the LSU register before the completion arbiter writes
    // the physical register. Wake dependent ALU work from that stable result to avoid a CDB cycle.
    val completedLoadIndex = lsu.io.complete.bits.token.index
    val completedLoadEntry = issueEntries(completedLoadIndex)
    val completedLoadBypass = p.loadCompletionBypass.B && lsu.io.complete.valid &&
        !lsu.io.complete.bits.exception &&
        memoryLive(completedLoadIndex) &&
        completedLoadEntry.renamed.token.asUInt === lsu.io.complete.bits.token.asUInt &&
        completedLoadEntry.request.memory && !completedLoadEntry.request.store &&
        !completedLoadEntry.request.atomic && completedLoadEntry.renamed.writesRd
    val wordPreviewBypass = p.mulWordPreviewBypass.B && multiplier.io.wordPreview.valid &&
        !multiplier.io.wordPreview.bits.exception &&
        issueEntries(multiplier.io.wordPreview.bits.token.index).renamed.token.asUInt ===
            multiplier.io.wordPreview.bits.token.asUInt &&
        issueEntries(multiplier.io.wordPreview.bits.token.index).renamed.writesRd
    val wordPreviewDestination = issueEntries(multiplier.io.wordPreview.bits.token.index).renamed.destination
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
    def issueOperandReady(index: UInt, localReady: Option[Bool] = None): Bool =
        IssueOperandReadiness(index, localReady.getOrElse(operandReady(index)),
            (if (p.registeredLoadResultReady) 0.U.asTypeOf(Valid(UInt(p.physBits.W))) else loadIssueWake),
            executionWake.toSeq)
    def issueOperandValue(index: UInt, stored: UInt): UInt = {
        val hits = executionWake.map(wake => wake.valid && wake.bits === index)
        val nonLoad = Mux(hits.reduce(_ || _), Mux1H(hits.zip(executionData)), stored)
        if (p.registeredLoadResultReady) {
            val held = lsu.io.heldLoadValue.get
            val loadHits = held.map(h => h.valid && h.bits.destination === index)
            Mux(loadHits.reduce(_ || _), Mux1H(loadHits.zip(held.map(_.bits.data))), nonLoad)
        } else Mux(loadIssueHit(index), lsu.io.complete.bits.data, nonLoad)
    }
    if (p.registeredLoadIssueForwarding) {
        // Invalid completion payload is unspecified (including its index). A when
        // does not prevent combinational assertion expressions being evaluated.
        val promisedIndex = Mux(loadIssueWake.valid, lsu.io.complete.bits.token.index, 0.U)
        val promisedEntry = issueEntries(promisedIndex)
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
    if (p.registeredLoadResultReady) {
        for (slot <- 0 until p.memoryEntries) {
            val holder = lsu.io.heldLoadValue.get(slot)
            val token = lsu.io.owner(slot)
            val index = Mux(holder.valid, token.index, 0.U)
            when(holder.valid) {
                assert(lsu.io.phase(slot) === 3.U && memoryLive(index) &&
                    issueEntries(index).renamed.token.asUInt === token.asUInt &&
                    issueEntries(index).request.memory && !issueEntries(index).request.store &&
                    !issueEntries(index).request.atomic && issueEntries(index).renamed.writesRd &&
                    issueEntries(index).renamed.destination === holder.bits.destination &&
                    holder.bits.destination =/= 0.U,
                    "raw held load value must retain its live full-token memory owner and exact destination")
                for (other <- 0 until slot) {
                    assert(!lsu.io.heldLoadValue.get(other).valid ||
                        lsu.io.heldLoadValue.get(other).bits.destination =/= holder.bits.destination,
                        "raw successful load holders must have unique physical destinations")
                }
                for (wake <- executionWake) {
                    assert(!wake.valid || wake.bits =/= holder.bits.destination,
                        "every raw held load destination must be distinct from all ALU promises")
                }
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
        val entry = issueEntries(i)
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
            ownerReady.map(_.io.ready1(i)).getOrElse(operandReady(source1)),
            issueOperandReady(source1, if (p.ownerLocalIssueReady) ownerReady.map(_.io.ready1(i)) else None))
        val source2Ready = entry.request.useImmediate || Mux(entry.request.memory,
            ownerReady.map(_.io.ready2(i)).getOrElse(operandReady(source2)),
            issueOperandReady(source2, if (p.ownerLocalIssueReady) ownerReady.map(_.io.ready2(i)) else None))
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
        !ledger.io.recovering && !blockPostedStart &&
        (!p.postedStoreMerge.B || postedBusy || !io.memoryBusy)
    fastStoreValid := fastStoreCandidate && !ledger.io.recoveryAccepted && !ledger.io.headException.valid
    fastStoreRequest.address := fastAddress
    fastStoreRequest.size := fastSize
    fastStoreRequest.data := storeData(head) << Cat(fastAddress(2, 0), 0.U(3.W))
    fastStoreRequest.mask := byteLanes(fastSize, fastAddress)
    fastStoreRequest.write := true.B
    fastProof.foreach { proof =>
        proof := 0.U.asTypeOf(proof)
        proof.valid := fastStoreValid
        proof.bits.token.index := headRenamed.token.index
        proof.bits.token.tag := headRenamed.token.tag
        proof.bits.epoch := io.posted.get.contextEpoch
        proof.bits.address := fastStoreRequest.address
        proof.bits.data := fastStoreRequest.data
        proof.bits.size := fastStoreRequest.size
        proof.bits.mask := fastStoreRequest.mask
        proof.bits.headAuthorized := true.B
        proof.bits.physicalPmpAllowed := true.B
        proof.bits.originalPhysical := true.B
        proof.bits.integerOrigin := true.B
    }
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
    val residentMemoryStartAllowed = if (p.residentMemoryPayloadReuse) Some(WireDefault(false.B)) else None
    val proofFrontier = if (p.memoryProofFrontier) Some(Module(new MemoryProofFrontier(p))) else None
    val pendingStoreProof = if (p.pendingVirtualStoreProof) Some(Module(new PendingVirtualStoreProof(p, p.registeredPendingStoreQuery))) else None
    val pendingStoreCredit = if (p.pendingVirtualStoreProof) Some(Module(new PendingStoreEarlyLoadCredit(p))) else None
    val pendingStoreRelied = WireDefault(0.U(p.pendingVirtualStoreProofSlots.W))
    val frontierChoice = WireDefault(false.B)
    val frontierReserve = WireDefault(false.B)
    val stagedMemoryMetadata = if (p.memoryProofFrontier) Some(Reg(new IntegerIssueEntry(p))) else None
    val proofOwnerClear = VecInit((0 until p.robEntries).map { i =>
        killed(i) || ledger.io.commit.map(c => c.valid && c.bits.token.index === i.U).reduce(_ || _) ||
            ledger.io.renamed.map(r => r.valid && r.bits.token.index === i.U).reduce(_ || _)
    }).asUInt
    proofFrontier.foreach { f =>
        f.io.head := head
        f.io.pending := pending.asUInt
        f.io.memoryLive := memoryLive.asUInt
        f.io.ordinary := VecInit(issueEntries.map(e => e.request.memory && !e.request.atomic && !e.request.system &&
            !e.request.mulDiv && !e.request.fetchFault && !e.request.fetchPageFault &&
            e.request.operation === IntegerOp.add && e.request.controlFlow === ControlFlow.none)).asUInt
        f.io.stores := VecInit(issueEntries.map(_.request.store)).asUInt
        f.io.systems := VecInit((0 until p.robEntries).map(i =>
            (pending(i) && issueEntries(i).request.system) || (memoryLive(i) && issueEntries(i).request.atomic))).asUInt
        f.io.canonicalLoads := memoryCanonical.get.asUInt
        f.io.clearOwners := proofOwnerClear
        f.io.pause := interruptDrain || reserveSystem || contextMemoryEpoch || fpMemoryEpoch ||
            ledger.io.recovering || !virtualized
        f.io.flushQueries := ledger.io.recovering || ledger.io.recoveryAccepted || contextMemoryEpoch ||
            interruptDrain || reserveSystem
        f.io.queryEligible := VecInit((0 until p.robEntries).map { i =>
            pending(i) && memoryLive(i) && Mux(issueEntries(i).request.store, storeAddressKnown(i),
                ownerReady.map(_.io.ready1(i)).getOrElse(operandReady(Mux(pending(i), issueEntries(i).renamed.source1, 0.U))))
        }).asUInt
        f.io.resultToken := issueEntries(f.io.resultIndex).renamed.token
        f.io.precheck <> io.loadPrecheck.get
        f.io.pmpState := pmpState
        f.io.privilege := dataPrivilege
        f.io.consume.valid := lsu.io.start.fire
        f.io.consume.bits := lsu.io.start.bits.token
        f.io.frontierAccepted := lsu.io.start.fire && frontierChoice
    }
    val memoryCandidates = (0 until p.robEntries).map { i =>
        val c            = Wire(new Candidate)
        val entry        = issueEntries(i)
        // Invalid queue slots are uninitialized. Do not use their stale IDs to
        // address the compact (48-entry, not 64-entry) PRF in the new planner.
        val source1 = if (p.parallelMemoryPreparation) Mux(pending(i), entry.renamed.source1, 0.U)
            else entry.renamed.source1
        val source2 = if (p.parallelMemoryPreparation) Mux(pending(i), entry.renamed.source2, 0.U)
            else entry.renamed.source2
        val sourcesReady = ownerReady.map(_.io.ready1(i)).getOrElse(operandReady(source1)) &&
            (!(entry.request.store || entry.request.atomic) ||
                ownerReady.map(_.io.ready2(i)).getOrElse(operandReady(source2)))
        c.valid := pending(i) && entry.request.memory && (!entry.request.store || memoryPreparationAtHead(i)) &&
            !(directStoreReserve && memoryPreparationAtHead(i)) &&
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
            val originalMemoryMask = VecInit(memoryCandidates.map(_.valid)).asUInt
            // Reconstructed default-off experiment: prefill the existing stage only
            // when the original candidate pool is empty BEFORE issued-owner exclusion.
            // An issued original candidate must never expose a younger store fallback.
            val preparationMask = if (p.preparedStoreLookahead) {
                val preparedStoreMask = VecInit((0 until p.robEntries).map { i =>
                    val entry = issueEntries(i)
                    pending(i) && memoryLive(i) && !memoryPreparationAtHead(i) &&
                        entry.renamed.token.index === i.U &&
                        entry.request.memory && entry.request.store && !entry.request.atomic &&
                        !entry.request.system && !entry.request.mulDiv &&
                        entry.request.controlFlow === ControlFlow.none &&
                        entry.request.operation === IntegerOp.add &&
                        !entry.request.fetchFault && !entry.request.fetchPageFault &&
                        storePrepared(i) && storeAddressKnown(i) && storeSafeRange(i) && !virtualized
                }).asUInt
                if (p.postedPreparationPriority) {
                    val originalPreparationMask = Mux(originalMemoryMask.orR, originalMemoryMask, preparedStoreMask)
                    // Decode-only qualification of EVERY original candidate, before issued-owner exclusion.
                    // Addresses/PMP are deliberately not inspected here; actual launch and seal gates stay below.
                    val allOriginalLoads = (0 until p.robEntries).map { i =>
                        val request = issueEntries(i).request
                        !originalMemoryMask(i) || (request.memory && !request.store && !request.atomic &&
                            !request.system && !request.mulDiv && request.controlFlow === ControlFlow.none &&
                            request.operation === IntegerOp.add && !request.fetchFault && !request.fetchPageFault)
                    }.reduce(_ && _)
                    val postedPreparationWindow = postedBusy && !virtualized && originalMemoryMask.orR &&
                        allOriginalLoads && !blockPostedStart && !interruptDrain && !contextMemoryEpoch &&
                        !fpMemoryEpoch && !ledger.io.recovering
                    // Keep both pools in the existing circular age order: older loads and head stores win.
                    // No P-only priority, saved owner, new rank/port, or launch/ready/seal feedback.
                    Mux(postedPreparationWindow, originalMemoryMask | preparedStoreMask, originalPreparationMask)
                } else Mux(originalMemoryMask.orR, originalMemoryMask, preparedStoreMask)
            } else originalMemoryMask
            if (p.residentMemoryPayloadReuse) {
                val residentIndex = stagedMemoryIndex.get
                val residentToken = stagedMemoryToken.get
                val residentEntry = issueEntries(residentIndex)
                // Liveness is independent of E: an accepted S can be absent from
                // the new preparation pool. Only reuse additionally needs E.
                val residentLive = stagedMemoryValid.get && pending(residentIndex) &&
                    residentToken.index === residentIndex &&
                    residentEntry.renamed.token.asUInt === residentToken.asUInt
                residentMemoryStartAllowed.get := residentLive &&
                    lsu.io.start.bits.token.asUInt === residentToken.asUInt
                val planner = Module(new ResidentMemoryPreparationSelector(p,
                    predecodedHead = p.registeredIssueHeadMask))
                planner.io.eligible := preparationMask
                planner.io.head := head
                planner.io.headMask.foreach(_ := issueHeadMask.get)
                planner.io.resident.valid := residentLive
                planner.io.resident.bits := residentIndex
                planner.io.issued := memoryIssued
                val owner = planner.io.freshOwner
                def selected(payloads: Seq[UInt]): UInt = CircularIssueSelector.selectPayload(owner, payloads)
                val freshEntry = readIssue(planner.io.freshIndex, "memoryPreparationFresh", Set("immediate"),
                    Some(owner))
                val source1 = MemoryPreparationLocality.sourceId(freshEntry.renamed.source1,
                    planner.io.freshValid, p.directRank0MemorySourceIds)
                val source2 = MemoryPreparationLocality.sourceId(freshEntry.renamed.source2,
                    planner.io.freshValid, p.directRank0MemorySourceIds)
                val saved = planner.io.freshValid && freshEntry.request.store && (owner & storePrepared.asUInt).orR
                val freshAddress = Mux(saved, selected(storeAddress.toSeq),
                    TimingArithmetic.add64(operandValue(source1), freshEntry.request.immediate))
                val freshData = Mux(saved, selected(storeData.toSeq), operandValue(source2))
                val preparedValid = planner.io.selectedValid
                stagedMemoryValid.get := preparedValid
                when(preparedValid) { stagedMemoryIndex.get := planner.io.selectedIndex }
                when(preparedValid || p.unconditionalMemoryPayloadCapture.B) {
                    stagedMemoryToken.get := Mux(planner.io.useResident, residentToken, freshEntry.renamed.token)
                    stagedMemoryAddress.get := Mux(planner.io.useResident, stagedMemoryAddress.get, freshAddress)
                    stagedMemoryData.get := Mux(planner.io.useResident, stagedMemoryData.get, freshData)
                    stagedMemorySize.get := Mux(planner.io.useResident, stagedMemorySize.get,
                        freshEntry.request.memorySize)
                }
                // Invariant witnesses use existing IDs/events/registers only.
                // Calling readPhysical/operandValue/readIssue here would add a
                // hidden observation read and invalidate the 14 -> 12 contract.
                when(memoryIssued) {
                    assert(residentLive && lsu.io.start.bits.token.asUInt === residentToken.asUInt,
                        "resident reuse permits only an exact live staged full-token memory start")
                }
                when(residentLive) {
                    assert(stagedMemorySize.get === residentEntry.request.memorySize,
                        "resident transfer size must remain immutable for its full token")
                    when(residentEntry.request.store && storePrepared(residentIndex)) {
                        assert(stagedMemoryAddress.get === storeAddress(residentIndex) &&
                            stagedMemoryData.get === storeData(residentIndex),
                            "same-token prepared-store transition must preserve resident VA and data")
                    }
                }
                val rawNeeded = residentLive && !killed(residentIndex) &&
                    !(residentEntry.request.store && storePrepared(residentIndex))
                val rawSource1 = Mux(rawNeeded, residentEntry.renamed.source1, 0.U)
                val rawSource2 = Mux(rawNeeded, residentEntry.renamed.source2, 0.U)
                val needsData = residentEntry.request.store || residentEntry.request.atomic
                when(rawNeeded) {
                    assert(rawSource1 < p.physicalRegs.U && rawSource2 < p.physicalRegs.U,
                        "live resident sources must remain inside the physical register file")
                    assert(ready(rawSource1) && (!needsData || ready(rawSource2)),
                        "resident raw operands must have been captured from registered-ready sources")
                    def overlaps(address: UInt): Bool =
                        (rawSource1 =/= 0.U && address === rawSource1) ||
                            (needsData && rawSource2 =/= 0.U && address === rawSource2)
                    for (reserve <- readyUpdate.get.io.reserve) {
                        assert(!reserve.valid || !overlaps(reserve.bits),
                            "a surviving pending resident source cannot be reallocated")
                    }
                    for (write <- physicalWrites.get) {
                        assert(!write.valid || !overlaps(write.bits.address),
                            "a registered-ready resident raw source cannot receive another accepted write")
                    }
                }
            } else {
                val planner = Module(new MemoryPreparationSelector(p, parallelRanks = p.parallelMemoryPayload,
                    predecodedHead = p.registeredIssueHeadMask))
                // This selects payload preparation only. Existing full-token/head/PMP,
                // interrupt and recovery checks below still authorize every LSU start.
                planner.io.eligible := preparationMask
                planner.io.head := head
                planner.io.headMask.foreach(_ := issueHeadMask.get)
                planner.io.issued := memoryIssued
                planner.io.issuedIndex := (if (p.memoryProofFrontier) lsu.io.start.bits.token.index else stagedMemoryIndex.get)
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
                        operands.io.source1(slot) := issueEntries(slot).renamed.source1
                        operands.io.source2(slot) := issueEntries(slot).renamed.source2
                    }
                }
                val secondValid = proofFrontier.map(_.io.queryOwner.valid).getOrElse(planner.io.secondValid)
                val secondIndex = proofFrontier.map(_.io.queryOwner.bits).getOrElse(planner.io.secondIndex)
                val candidates = Seq((planner.io.firstValid, planner.io.firstIndex),
                    (secondValid, secondIndex)).zipWithIndex.map { case ((valid, index), rank) =>
                    val owner = if (rank == 0) planner.io.firstOwner else
                        (if (p.memoryProofFrontier) UIntToOH(index, p.robEntries) else planner.io.secondOwner)
                    def selected(payloads: Seq[UInt]): UInt = CircularIssueSelector.selectPayload(owner, payloads)
                    val entry = readIssue(index, s"memoryPreparation$rank", Set("immediate"),
                        if (p.parallelMemoryPayload) Some(owner) else None)
                    val queryRank = p.memoryProofFrontier && rank == 1
                    val saved = valid && entry.request.store && (if (queryRank) storeAddressKnown(index)
                        else if (p.parallelMemoryPayload) (owner & storePrepared.asUInt).orR else storePrepared(index))
                    // Parallel rank owners already mask source IDs to zero when absent.
                    // Each direct flag removes only that rank's redundant ID clear.
                    // Full owner/readiness and final launch authority stay unchanged.
                    val directSourceIds = memoryPreparationDirectSourceRanks(rank)
                    val source1 = MemoryPreparationLocality.sourceId(entry.renamed.source1, valid, directSourceIds)
                    val source2 = MemoryPreparationLocality.sourceId(entry.renamed.source2, valid, directSourceIds)
                    val savedAddress = if (p.parallelMemoryPayload) selected(storeAddress.toSeq) else storeAddress(index)
                    val savedData = if (p.parallelMemoryPayload) selected(storeData.toSeq) else storeData(index)
                    val left = memoryOperands.map(_.io.left(rank)).getOrElse(operandValue(source1))
                    val right = if (queryRank) 0.U(64.W)
                        else memoryOperands.map(_.io.right(rank)).getOrElse(operandValue(source2))
                    val summed = if (p.parallelMemoryAddressSum)
                        TimingArithmetic.add64(left, entry.request.immediate) else left + entry.request.immediate
                    val address = Mux(saved, savedAddress, summed)
                    val data = Mux(saved, savedData, right)
                    if (queryRank) {
                        proofFrontier.get.io.query.token := entry.renamed.token
                        proofFrontier.get.io.query.address := address
                        proofFrontier.get.io.query.size := entry.request.memorySize
                        proofFrontier.get.io.query.write := entry.request.store
                    }
                    if (p.memoryProofFrontier && rank == 0) { stagedMemoryMetadata.get := entry }
                    (entry.renamed.token, address, data, entry.request.memorySize)
                }
                // The late start.fire only selects fully computed payloads. It must
                // not choose a PRF port or enter the 64-bit effective-address adder.
                val preparedValid = if (p.memoryProofFrontier) planner.io.firstValid &&
                    !(memoryIssued && planner.io.firstIndex === lsu.io.start.bits.token.index) &&
                    !proofOwnerClear(planner.io.firstIndex) else planner.io.selectedValid
                val preparedIndex = if (p.memoryProofFrontier) planner.io.firstIndex else planner.io.selectedIndex
                val useSecond = if (p.memoryProofFrontier) false.B else planner.io.useSecond
                stagedMemoryValid.get := preparedValid
                when(preparedValid) { stagedMemoryIndex.get := preparedIndex }
                // Invalid payloads cannot authorize a request: valid, owner token,
                // and pending still gate every use. Avoid a late 64-bit clock enable.
                when(preparedValid || p.unconditionalMemoryPayloadCapture.B) {
                    stagedMemoryToken.get := Mux(useSecond, candidates(1)._1, candidates(0)._1)
                    stagedMemoryAddress.get := Mux(useSecond, candidates(1)._2, candidates(0)._2)
                    stagedMemoryData.get := Mux(useSecond, candidates(1)._3, candidates(0)._3)
                    stagedMemorySize.get := Mux(useSecond, candidates(1)._4, candidates(0)._4)
                }
            }
        } else {
            val preparation = readIssue(memoryPrechoice.index, "memoryPreparation", Set("immediate"))
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
            (if (p.memoryProofFrontier) !proofOwnerClear(stagedMemoryIndex.get)
             else issueEntries(stagedMemoryIndex.get).renamed.token.asUInt === stagedMemoryToken.get.asUInt)
        memoryChoice.index := stagedMemoryIndex.get
        memoryChoice.age := stagedMemoryIndex.get - head
    } else {
        memoryChoice := memoryPrechoice
    }
    val memoryEntry   = if (p.memoryProofFrontier) stagedMemoryMetadata.get else readIssue(memoryChoice.index, "memoryIssue",
        Set("pc") ++ (if (!p.registeredMemoryAddress) Set("immediate") else Set.empty[String]) ++
            (if (p.fastBufferedStoreRetire) Set("instruction") else Set.empty[String]))
    val memorySize    = stagedMemorySize.getOrElse(Mux(memoryChoice.valid, memoryEntry.request.memorySize, 0.U))
    val memorySource1 = Mux(memoryChoice.valid, memoryEntry.renamed.source1, 0.U)
    val memorySource2 = Mux(memoryChoice.valid, memoryEntry.renamed.source2, 0.U)
    val savedStore    = memoryChoice.valid && memoryEntry.request.store && storePrepared(memoryChoice.index)
    val address       = if (p.registeredMemoryAddress) stagedMemoryAddress.get else
        Mux(savedStore, storeAddress(memoryChoice.index), operandValue(memorySource1) + memoryEntry.request.immediate)
    val actualMemoryIndex = proofFrontier.map(f => Mux(frontierChoice, f.io.frontier.bits.token.index, memoryChoice.index))
        .getOrElse(memoryChoice.index)
    val actualMemoryEntry = if (p.memoryProofFrontier) readIssue(actualMemoryIndex, "memoryIssue", Set("pc")) else memoryEntry
    proofFrontier.foreach { f =>
        f.io.selected.valid := memoryChoice.valid
        f.io.selected.bits := memoryEntry.renamed.token
    }
    val loadPreparation = if (p.virtualRamLoadPrecheck && !p.memoryProofFrontier && !p.pendingVirtualStoreProof)
        Some(Module(new VirtualRamLoadPreparation(p))) else None
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
    val pendingStoreDataReady = (0 until p.robEntries).map { i =>
        // Policy uses registered PRF readiness only, including profiles without
        // owner-local mirrors; completion/preview bypass cannot extend this cone.
        storePrepared(i) || ownerReady.map(_.io.ready2(i)).getOrElse(
            ready(Mux(pending(i), issueEntries(i).renamed.source2, 0.U)))
    }
    pendingStoreProof.foreach { bank =>
        bank.io.head := head
        bank.io.clearOwners := proofOwnerClear
        bank.io.pause := interruptDrain || reserveSystem || contextMemoryEpoch || fpMemoryEpoch ||
            ledger.io.recovering || !virtualized
        bank.io.flushQueries := ledger.io.recovering || contextMemoryEpoch ||
            interruptDrain || reserveSystem
        bank.io.loadCandidate.valid := memoryChoice.valid && virtualized &&
            !memoryEntry.request.store && !memoryEntry.request.atomic
        bank.io.loadCandidate.bits.token := memoryEntry.renamed.token
        bank.io.loadCandidate.bits.address := address
        bank.io.loadCandidate.bits.size := memorySize
        bank.io.pmpState := pmpState
        bank.io.privilege := dataPrivilege
        bank.io.precheck <> io.loadPrecheck.get
        bank.io.consume.valid := lsu.io.start.fire
        bank.io.consume.bits := lsu.io.start.bits.token
        bank.io.bind := Mux(lsu.io.start.valid && !lsu.io.start.bits.store &&
            lsu.io.start.bits.precheckedLoad, pendingStoreRelied, 0.U)
        for (i <- 0 until p.robEntries) {
            val entry = issueEntries(i)
            val owner = bank.io.owners(i)
            PendingStoreProofRobOwner.connect(owner, entry.renamed.token, entry.request,
                pending(i), memoryLive(i), storeAddressKnown(i), storeAddress(i), storeByteLanes(i), i)
        }
        bank.io.queryEligible := VecInit((0 until p.robEntries).map { i =>
            bank.io.loadCandidate.valid && ages(i) < memoryChoice.age && !pendingStoreDataReady(i)
        }).asUInt
    }
    val originalLoadPrepared = loadPreparation.map(_.io.prepared)
        .orElse(pendingStoreProof.map(_.io.loadPrepared))
    val bankProof = proofFrontier.map(_.io.selectedProof)
    val bankProofMatches = bankProof.map(r => r.valid && memoryChoice.valid &&
        r.bits.token.asUInt === memoryEntry.renamed.token.asUInt && r.bits.payload.address === address &&
        r.bits.payload.size === memorySize && r.bits.payload.write === memoryEntry.request.store).getOrElse(false.B)
    val selectedPhysicalAddress = bankProof.map(_.bits.payload.physicalAddress)
        .getOrElse(originalLoadPrepared.map(_.bits.physicalAddress).getOrElse(0.U))
    val selectedTranslationEpoch = bankProof.map(_.bits.epoch)
        .getOrElse(originalLoadPrepared.map(_.bits.epoch).getOrElse(0.U))
    val preparedLoadMatches = (if (p.memoryProofFrontier) bankProofMatches else originalLoadPrepared.map { result =>
        result.valid && memoryChoice.valid && result.bits.token.asUInt === memoryEntry.renamed.token.asUInt &&
            result.bits.address === address && result.bits.size === memorySize
    }.getOrElse(false.B))
    val precheckedLoad = preparedLoadMatches && virtualized &&
        !memoryEntry.request.store && !memoryEntry.request.atomic &&
        (if (p.memoryProofFrontier) true.B else originalLoadPrepared.map(_.bits.allowed).getOrElse(false.B))
    // Preparation is opportunistic. A ready head never waits for an optional certificate: it uses
    // the existing serial virtual path unless a matching registered proof is already available.
    // Only younger speculation requires a positive proof. This preserves cold/dependent head-load
    // latency without a combinational TLB/PMP bypass. A serial start clears pending below, so a
    // later proof for that full token cannot relaunch it or change the accepted LSU owner's mode.
    val canonicalAddress = Mux(virtualized,
        selectedPhysicalAddress, address)
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
    // One actual accepted head store, retaining the original VA and ordinary serial LSU ownership.
    // Proof output depends on registered state only; same-edge kill/fault clears it at the next edge.
    val canonicalStoreTracker = if (p.canonicalVirtualStoreOverlap) Some(Module(new CanonicalStoreTracker(p))) else None
    canonicalStoreTracker.foreach { tracker =>
        val token = tracker.io.owner
        val index = Mux(tracker.io.tracked, token.index, 0.U)
        tracker.io.ownerLive := tracker.io.tracked && memoryProtected && ledger.io.headValid &&
            (if (registerCanonicalStoreEvent) !ledger.io.headDone else true.B) &&
            memoryOwner.asUInt === token.asUInt && headRenamed.token.asUInt === token.asUInt &&
            memoryLive(index) && !pending(index) && issueEntries(index).renamed.token.asUInt === token.asUInt &&
            issueEntries(index).request.memory && issueEntries(index).request.store && !issueEntries(index).request.atomic &&
            !issueEntries(index).request.system
        tracker.io.epoch := io.loadPrecheck.get.epoch
        tracker.io.stable := io.loadPrecheck.get.stable && !contextMemoryEpoch
        tracker.io.checked := io.canonicalStore.get.checked
        val retired = ledger.io.commit.map(c => c.valid && c.bits.token.asUInt === token.asUInt).reduce(_ || _)
        // The staged mode conservatively disposes proof for every matching
        // consumed LSU result, even when the ROB rejects that result. The default
        // retains its existing exception-only disposal contract.
        val disposed = lsu.io.complete.fire &&
            (if (registerCanonicalStoreEvent) true.B else lsu.io.complete.bits.exception) &&
            lsu.io.complete.bits.token.asUInt === token.asUInt
        tracker.io.invalidate := ledger.io.recoveryAccepted || ledger.io.recovering ||
            headTrapAccepted || headSystemAccepted || contextMemoryEpoch || reserveSystem ||
            interruptDrain || (tracker.io.tracked && (killed(index) || retired || disposed))
        lsu.io.relaxStoreOwner.get.valid := tracker.io.certificate.valid
        lsu.io.relaxStoreOwner.get.bits := tracker.io.certificate.bits.origin.token
    }
    // Certificate.valid retains the complete indexed ownerLive check above.
    // Allocation alone makes a row live and writes its own token index. Keep
    // all class/live gates: invalid queue payload is unspecified.
    val certFor = (0 until p.robEntries).map { i =>
        canonicalStoreTracker.map(t => t.io.certificate.valid && memoryLive(i) &&
            issueEntries(i).request.memory && issueEntries(i).request.store && !issueEntries(i).request.atomic &&
            (if (shareCanonicalStoreOwnerMatch) t.io.certificate.bits.origin.token.index === i.U
             else issueEntries(i).renamed.token.asUInt === t.io.certificate.bits.origin.token.asUInt)).getOrElse(false.B)
    }
    proofFrontier.foreach { f =>
        f.io.canonicalStores := VecInit(certFor).asUInt
        f.io.checkedStore := canonicalStoreTracker.get.io.certificate
    }
    // Preproof is distinct from actual checked-store ownership. Compute each
    // wide PA comparison once, then distribute only Boolean owner matches.
    val pendingStoreRowDisjoint = pendingStoreProof.map { bank =>
        bank.io.proofs.map(proof => proof.valid && AlignedMemoryDisjoint.withLanes(
            canonicalAddress, loadAligned, loadMask, proof.bits.payload.physicalAddress(63, 3), proof.bits.payload.mask))
    }
    pendingStoreProof.foreach { bank =>
        bank.io.proofs.foreach(proof => PendingStoreProofRobMapping.assertIndexedOwner(
            proof, issueEntries(proof.bits.token.index).renamed.token))
    }
    val pendingStoreProofFor = (0 until p.robEntries).map { i =>
        pendingStoreProof.map(bank => bank.io.proofs.map(proof => PendingStoreProofRobMapping.matches(proof, i))
            .reduce(_ || _)).getOrElse(false.B)
    }
    val pendingStoreDisjointFor = (0 until p.robEntries).map { i =>
        pendingStoreProof.map(bank => (0 until p.pendingVirtualStoreProofSlots).map(r =>
            pendingStoreRowDisjoint.get(r) && PendingStoreProofRobMapping.matches(bank.io.proofs(r), i))
            .reduce(_ || _)).getOrElse(false.B)
    }
    val pendingStoreOlder = VecInit((0 until p.robEntries).map(i => memoryLive(i) && pending(i) &&
        issueEntries(i).request.store && ages(i) < memoryChoice.age)).asUInt
    val pendingStoreBypass = p.pendingVirtualStoreProof.B && precheckedLoad && memoryChoice.index =/= head &&
        pendingStoreOlder.orR
    val pendingStoreOfferAllowedFor = if (p.pendingReadyStoreBypass) Some((0 until p.robEntries).map { i =>
        // The registered boundary names the current pre-edge head, including wrap.
        // Readiness may relax only a new offer; accepted LSU owners and bound proofs
        // remain unchanged when this store later becomes the actual head.
        val isHead = issueHeadMask.map(mask => mask(i) &&
            (if (i == 0) true.B else !mask(i - 1))).getOrElse(i.U === head)
        assert(isHead === (i.U === head), "ready-store bypass must use the current ROB head")
        pendingStoreProofFor(i) && (!pendingStoreDataReady(i) || !isHead)
    }) else None
    val pendingStoreNewOfferAllowed = !pendingStoreBypass || (pendingStoreCredit.map(_.io.available).getOrElse(false.B) &&
        (0 until p.robEntries).map(i => !pendingStoreOlder(i) ||
            pendingStoreOfferAllowedFor.map(_(i)).getOrElse(
                pendingStoreProofFor(i) && !pendingStoreDataReady(i))).reduce(_ && _))
    pendingStoreProof.foreach { bank =>
        pendingStoreRelied := VecInit(bank.io.proofs.map(proof => pendingStoreBypass && proof.valid &&
            pendingStoreOlder(proof.bits.token.index))).asUInt
    }
    val pendingStoreSelected = WireDefault(0.U.asTypeOf(new MemoryAddressProof(p)))
    val pendingStoreBoundMatches = pendingStoreProof.map { bank =>
        val matches = VecInit((0 until p.pendingVirtualStoreProofSlots).map(r => bank.io.bound(r) &&
            bank.io.proofs(r).valid && bank.io.proofs(r).bits.token.asUInt === memoryEntry.renamed.token.asUInt &&
            bank.io.proofs(r).bits.payload.address === address && bank.io.proofs(r).bits.payload.size === memorySize))
        // Bound row identities are registered and unique in the proof bank.
        // Select immutable payload before late owner/epoch revalidation; the
        // original full-token/VA/size matches remain the only authorization.
        pendingStoreSelected := BoundStoreProofPayload.select(bank.io.bound,
            bank.io.proofs.map(_.bits).toSeq, memoryEntry.renamed.token.index)
        if (p.boundHeadStoreOverlap) {
            assert(PopCount(matches) <= 1.U, "at most one bound proof may name the exact staged store")
        }
        matches.asUInt.orR
    }.getOrElse(false.B)
    val physicalStoreConflict = (0 until p.robEntries)
        .map { i =>
            // Safe prepared stores and naturally aligned loads are single-beat
            // byte intervals. Unaligned younger loads wait for precise head
            // fault handling; they cannot use a truncated lane mask to bypass.
            val disjoint = AlignedMemoryDisjoint.withLanes(canonicalAddress, loadAligned, loadMask,
                storeAddress(i)(63, 3), storeByteLanes(i))
            val knownDisjoint = canonicalStoreTracker.map { tracker =>
                val checked = tracker.io.certificate.bits
                val canonicalDisjoint = certFor(i) && AlignedMemoryDisjoint.withLanes(
                    canonicalAddress, loadAligned, loadMask, checked.physicalAddress(63, 3), checked.mask)
                // A prepared virtual address is never compared with this load's physical address.
                Mux(precheckedLoad, canonicalDisjoint || pendingStoreDisjointFor(i),
                    storeAddressKnown(i) && storeSafeRange(i) && disjoint)
            }.getOrElse(storeAddressKnown(i) && storeSafeRange(i) && disjoint)
            memoryLive(i) && issueEntries(i).request.store && ages(i) < memoryChoice.age &&
            !knownDisjoint &&
            !(forwarding && issueEntries(i).renamed.token.asUInt === sourceStore.bits.token.asUInt)
        }
        .reduce(_ || _)
    // Actual canonical ownership stays unchanged. Only a pending ordinary store
    // with its separately retained exact write proof can discharge the new barrier.
    val olderUncanonicalMemory = memoryCanonical.map { known =>
        (0 until p.robEntries).map(i => memoryLive(i) && ages(i) < memoryChoice.age &&
            (if (p.canonicalVirtualStoreOverlap) Mux(issueEntries(i).request.store, !(certFor(i) || pendingStoreProofFor(i)), !known(i))
             else issueEntries(i).request.store || !known(i))).reduce(_ || _)
    }.getOrElse(false.B)
    val blockedByStore = physicalStoreConflict || (precheckedLoad && olderUncanonicalMemory)
    val unknownOlderStore = (0 until p.robEntries)
        .map(i => memoryLive(i) && issueEntries(i).request.store && ages(i) < memoryChoice.age && !storeAddressKnown(i))
        .reduce(_ || _)
    val speculative = !memoryEntry.request.store && !memoryEntry.request.atomic && ordinaryRam
    // Reserve before branch resolution to avoid a select -> redirect -> select combinational loop.
    val olderSystem = (0 until p.robEntries)
        .map(i =>
            ((pending(i) && issueEntries(i).request.system) || (memoryLive(i) && issueEntries(i).request.atomic)) &&
                ages(i) < memoryChoice.age
        )
        .reduce(_ || _)
    val postedEligible = p.postedStoreMerge.B && ledger.io.headValid && memoryChoice.index === head &&
        memoryEntry.renamed.token.asUInt === headRenamed.token.asUInt &&
        memoryEntry.request.store && !memoryEntry.request.atomic && !virtualized &&
        ordinaryRam && !pmpCheck.io.denied && AlignedMemoryDisjoint.aligned(address, memorySize)
    // First posted ownership drains all accepted CPU work. The opt-in staged head
    // may offer while only autonomous PF remains; cache admission still owns every
    // PF/MSHR/WB/response check. Once live, only eligible head physical stores may
    // continue. The blocked offer never counts as accepted work.
    val postedLaunchAllowed = !p.postedStoreMerge.B || (!blockPostedStart && !directStoreReserve &&
        Mux(postedBusy, postedEligible, !postedEligible ||
            (if (p.postedPrefetchHeadOffer) !cpuAcceptedMemoryBusy.get else !io.memoryBusy)))
    io.posted.foreach { posted =>
        // Lookahead prepares a younger safe store while an older ALU/branch is
        // still head. Preparation is not an ordered memory boundary: sealing
        // here would permanently prevent that store from joining once it really
        // becomes head. This exception grants no launch/proof authority; all
        // existing head/full-token/PMP checks above and below remain mandatory.
        // Virtual/IO/faulting stores still seal accepted ownership just as before.
        val preparedPhysicalStore = p.preparedStoreLookahead.B && memoryChoice.valid &&
            memoryChoice.index =/= head && savedStore &&
            memoryEntry.renamed.token.index === memoryChoice.index &&
            memoryEntry.request.store && !memoryEntry.request.atomic && !virtualized &&
            ordinaryRam && !pmpCheck.io.denied && AlignedMemoryDisjoint.aligned(address, memorySize)
        // This optional exception is only an unissued intent. The parameter contract
        // keeps memoryChoice.valid on the existing full staged-token/pending check.
        // A live non-head row is strictly younger in the current circular ROB window.
        // postedLaunchAllowed still blocks this load; stores may launch only at the
        // actual head, so no program-younger store can cross the deferred load.
        // Keep the old intent boundary when an unready head load/atomic causes
        // the selector to name a different, younger load.
        val deferredYoungerLoad = if (p.postedYoungerLoadSealDeferral) {
            PostedYoungerLoadSeal.defer(postedBusy, ledger.io.headValid, headRequest,
                memoryChoice.valid, memoryChoice.index =/= head, memoryLive(memoryChoice.index),
                pending(memoryChoice.index), memoryEntry.renamed.token.index === memoryChoice.index,
                memoryEntry.request, !virtualized, ordinaryRam, !pmpCheck.io.denied,
                AlignedMemoryDisjoint.aligned(address, memorySize))
        } else false.B
        posted.seal := recovery.valid || ledger.io.recovering || interruptDrain ||
            reserveSystem || contextMemoryEpoch ||
            (memoryChoice.valid && !postedEligible && !preparedPhysicalStore && !deferredYoungerLoad) ||
            (ledger.io.headValid && headRequest.system)
    }
    val originalMemoryEligible = postedLaunchAllowed && pendingStoreNewOfferAllowed &&
        !interruptDrain && !reserveSystem && !olderSystem && !fpMemoryEpoch && !contextMemoryEpoch &&
            memoryChoice.valid && io.commitEnable &&
            ((p.issueWidth > 1).B || !directStoreReserve) &&
            !ledger.io.recovering && (!memoryEntry.request.atomic || !io.memoryBusy) &&
            (if (p.registeredMemoryAddress) true.B else
                savedStore || (operandReady(memorySource1) &&
                    (!(memoryEntry.request.store || memoryEntry.request.atomic) || operandReady(memorySource2)))) &&
            (memoryChoice.index === head || (speculative && !blockedByStore)) &&
            (!proofFrontier.map(_.io.selectedBound).getOrElse(false.B) || bankProofMatches) &&
            !pendingStoreProof.map(bank => (0 until p.pendingVirtualStoreProofSlots).map(r =>
                bank.io.bound(r) && bank.io.proofs(r).bits.token.asUInt === memoryEntry.renamed.token.asUInt &&
                    !pendingStoreBoundMatches).reduce(_ || _)).getOrElse(false.B)
    val headDrainIntent = ledger.io.headValid && pending(head) && io.headProfile.operandsReady &&
        (headRequest.system || (headRequest.memory && (headRequest.store || headRequest.atomic ||
            !(memoryChoice.valid && memoryChoice.index === head && speculative))))
    proofFrontier.foreach { f =>
        frontierChoice := f.io.frontier.valid && !originalMemoryEligible && !headDrainIntent &&
            !interruptDrain && !reserveSystem && !fpMemoryEpoch && !contextMemoryEpoch && !postedBusy &&
            !blockPostedStart && !directStoreReserve && !ledger.io.recovering && io.commitEnable
        frontierReserve := frontierChoice && lsu.io.issueAvailable
    }
    val reserveMemory = (originalMemoryEligible && lsu.io.issueAvailable) || frontierReserve
    val youngerLoadCouldIssue = !interruptDrain && !reserveSystem && !olderSystem && !fpMemoryEpoch && !contextMemoryEpoch && memoryChoice.valid &&
        !memoryEntry.request.store && !memoryEntry.request.atomic && memoryChoice.index =/= head &&
        speculative && lsu.io.issueAvailable && io.commitEnable && !ledger.io.recovering &&
        !ledger.io.recoveryAccepted && !ledger.io.headException.valid && operandReady(memorySource1)
    // The only PC payload read belongs to actualMemoryEntry. A frontier winner has no
    // simultaneous original-candidate PC sample; never label its PC as the blocked owner.
    io.headProfile.candidateLoadPc := (if (p.memoryProofFrontier)
        Mux(frontierChoice, 0.U, actualMemoryEntry.request.rename.pc) else memoryEntry.request.rename.pc)
    io.headProfile.candidateLoadBlockedByStore := youngerLoadCouldIssue && blockedByStore && !frontierChoice
    io.headProfile.candidateLoadBlockedByUnknownStore := youngerLoadCouldIssue && blockedByStore &&
        unknownOlderStore && !frontierChoice
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
        memoryLive(i) && !pending(i) && issueEntries(i).request.memory &&
            !issueEntries(i).request.store && !issueEntries(i).request.atomic &&
            memoryCanonical.map(_(i)).getOrElse(true.B)
    }).asUInt
    val loadReplay = Wire(new Candidate)
    loadReplay.valid := replaySelector.io.valid
    loadReplay.index := replaySelector.io.index
    loadReplay.age := replaySelector.io.index - head
    val loadReplayToken = Mux1H((0 until p.robEntries).map { i =>
        replaySelector.io.oneHot(i) -> issueEntries(i).renamed.token
    })
    val loadReplayPc = readIssue(replaySelector.io.index, "loadReplay", Set("pc"),
        Some(replaySelector.io.oneHot)).request.rename.pc
    if (p.registeredLoadReplay) {
        // The check itself and every younger instruction remain nonretirable.
        // The optional full-token ROB limit releases only its strictly older
        // prefix; pending replay still keeps the inherited global hold.
        replayRetirementHold := (if (p.loadOrderOlderRetire) replayPendingValid.get
            else orderCheckValid || replayPendingValid.get)
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
    val actualOwnerMatches = if (p.memoryProofFrontier)
        (actualMemoryEntry.renamed.token.asUInt === Mux(frontierChoice,
            proofFrontier.map(_.io.frontier.bits.token).getOrElse(memoryEntry.renamed.token), memoryEntry.renamed.token).asUInt &&
            pending(actualMemoryIndex) && !proofOwnerClear(actualMemoryIndex))
        else if (p.residentMemoryPayloadReuse) residentMemoryStartAllowed.get else true.B
    lsu.io.start.valid := reserveMemory && actualOwnerMatches &&
        !(if (p.earlyRecoveryIssueBlock) earlyRecoveryIssueBlock else ledger.io.recoveryAccepted) &&
        !(if (p.earlyRecoveryIssueBlock) ledger.io.pendingException.valid else ledger.io.headException.valid)
    if (p.residentMemoryPayloadReuse) {
        // Independent of the new guard: it must never suppress a start that
        // the original non-frontier admission law would offer.
        val originalMemoryStart = reserveMemory &&
            !(if (p.earlyRecoveryIssueBlock) earlyRecoveryIssueBlock else ledger.io.recoveryAccepted) &&
            !(if (p.earlyRecoveryIssueBlock) ledger.io.pendingException.valid else ledger.io.headException.valid)
        when(originalMemoryStart) {
            assert(residentMemoryStartAllowed.get,
                "resident full-token guard must preserve every original memory start offer")
        }
    }
    memoryIssued                   := lsu.io.start.fire
    io.headProfile.storePrepared := ledger.io.headValid && headRequest.store && storePrepared(head)
    io.headProfile.memoryStarting := directStoreFire || (lsu.io.start.fire && actualMemoryIndex === head)
    io.headProfile.memorySlotAvailable := lsu.io.issueAvailable
    lsu.io.parallel                 := speculative || frontierChoice
    lsu.io.start.bits.forward.valid := forwarding
    lsu.io.start.bits.forward.bits  := sourceStore.bits.data
    lsu.io.issueDestination.foreach { destination =>
        destination.valid := memoryEntry.renamed.writesRd
        destination.bits := memoryEntry.renamed.destination
    }
    lsu.io.start.bits.token         := memoryEntry.renamed.token
    lsu.io.start.bits.pc            := actualMemoryEntry.request.rename.pc
    lsu.io.start.bits.address       := address
    lsu.io.start.bits.precheckedLoad := precheckedLoad
    lsu.io.start.bits.physicalAddress := selectedPhysicalAddress
    lsu.io.start.bits.translationEpoch := selectedTranslationEpoch
    lsu.io.start.bits.data          := (if (p.registeredMemoryAddress) stagedMemoryData.get else
        Mux(savedStore, storeData(memoryChoice.index), operandValue(memorySource2)))
    lsu.io.start.bits.atomic        := memoryEntry.request.atomic
    lsu.io.start.bits.atomicOp      := memoryEntry.request.atomicOp
    lsu.io.start.bits.store         := memoryEntry.request.store
    lsu.io.start.bits.size          := memorySize
    lsu.io.start.bits.unsigned      := memoryEntry.request.memoryUnsigned
    lsu.io.start.bits.accessDenied  := pmpCheck.io.denied && !virtualized
    lsu.io.start.bits.virtualized   := virtualized
    lsu.io.start.bits.frozenStoreProof.foreach { frozen =>
        frozen := 0.U.asTypeOf(frozen)
        if (p.memoryProofFrontier) {
            val proof = bankProof.get.bits
            frozen.valid := bankProofMatches && memoryEntry.request.store && !frontierChoice &&
                memoryChoice.index === head && virtualized && !memoryEntry.request.atomic
            frozen.bits.address := proof.payload.address
            frozen.bits.physicalAddress := proof.payload.physicalAddress
            frozen.bits.size := proof.payload.size
            frozen.bits.mask := proof.payload.mask
            when(lsu.io.start.fire && proofFrontier.get.io.selectedBound && !frontierChoice) {
                assert(bankProofMatches && (precheckedLoad || frozen.valid),
                    "all original and head routes must consume the current bound tuple")
            }
        }
        if (p.pendingVirtualStoreProof) {
            frozen.valid := pendingStoreBoundMatches && memoryEntry.request.store &&
                memoryChoice.index === head && virtualized && !memoryEntry.request.atomic
            frozen.bits.address := pendingStoreSelected.payload.address
            frozen.bits.physicalAddress := pendingStoreSelected.payload.physicalAddress
            frozen.bits.size := pendingStoreSelected.payload.size
            frozen.bits.mask := pendingStoreSelected.payload.mask
            when(lsu.io.start.fire && pendingStoreBoundMatches) {
                assert(frozen.valid && lsu.io.start.bits.canonicalStoreEpoch.get.valid &&
                    pendingStoreSelected.epoch === lsu.io.start.bits.canonicalStoreEpoch.get.bits,
                    "bound pending-store PA transfers only to the exact protected head-store owner")
            }
        }
    }
    lsu.io.boundHeadStoreOverlapQualified.foreach { qualified =>
        val frozen = lsu.io.start.bits.frozenStoreProof.get
        val epoch = lsu.io.start.bits.canonicalStoreEpoch.get
        // This permit uses only the staged candidate, saved bound proof, head
        // ownership and stable epoch. Original eligibility and the final
        // recovery/exception gate still authorize the actual start.
        qualified := memoryChoice.valid && ledger.io.headValid && !ledger.io.headDone && pending(head) &&
            memoryChoice.index === head && memoryEntry.renamed.token.asUInt === headRenamed.token.asUInt &&
            memoryEntry.request.memory && memoryEntry.request.store && virtualized &&
            !memoryEntry.request.atomic && !memoryEntry.request.system && !memoryEntry.request.mulDiv &&
            !memoryEntry.request.fetchFault && !memoryEntry.request.fetchPageFault &&
            !memoryProtected && !systemProtected && !postedBusy && !forwarding &&
            pendingStoreBoundMatches && frozen.valid && epoch.valid && io.loadPrecheck.get.stable &&
            pendingStoreSelected.epoch === epoch.bits && epoch.bits === io.loadPrecheck.get.epoch
        when(lsu.io.boundHeadStoreOverlapAccepted.get) {
            assert(qualified && originalMemoryEligible && !ledger.io.recoveryAccepted &&
                !ledger.io.pendingException.valid && !lsu.io.parallel,
                "bound overlap retains the exact head, original eligibility and final recovery/exception authority")
            assert(frozen.bits.address === address && frozen.bits.size === memorySize &&
                frozen.bits.mask === byteLanes(memorySize, address),
                "bound overlap captures the exact frozen virtual address, size and byte lanes")
            for (slot <- 0 until p.memoryEntries) {
                val owner = lsu.io.owner(slot)
                val index = Mux(lsu.io.live(slot), owner.index, 0.U)
                val age = (index - head)(p.robBits - 1, 0)
                when(lsu.io.live(slot)) {
                    // Assertion-only full-width current-generation witnesses.
                    // The functional path uses the proved noncancelled saved
                    // LSU-owner lifetime, not four dynamic ROB payload reads.
                    assert(memoryLive(index) && !pending(index) && memoryCanonical.get(index) &&
                        issueEntries(index).renamed.token.asUInt === owner.asUInt &&
                        issueEntries(index).request.memory && !issueEntries(index).request.store &&
                        !issueEntries(index).request.atomic && age =/= 0.U && age < ledger.io.occupancy &&
                        !killed(index),
                        "every admitted co-owner is an exact current younger canonical load, including done/error owners")
                }
            }
        }
    }
    pendingStoreCredit.foreach { credit =>
        credit.io.reserve.valid := lsu.io.start.valid && pendingStoreBypass
        credit.io.reserve.bits := lsu.io.start.bits.token
        credit.io.consume.valid := lsu.io.start.fire && pendingStoreBypass
        credit.io.consume.bits := lsu.io.start.bits.token
        credit.io.cancelReservation := 0.U.asTypeOf(credit.io.cancelReservation)
        for (slot <- 0 until p.memoryEntries) {
            credit.io.liveOwners(slot).valid := lsu.io.live(slot)
            credit.io.liveOwners(slot).bits := lsu.io.owner(slot)
        }
        // The existing ready-always completion sink means every committed LSU
        // offer is captured immediately. Downstream held offers belong to that
        // immutable accepted owner and no longer depend on live rs2 readiness.
        assert(!lsu.io.start.valid || lsu.io.start.ready,
            "pending-store proof integration never exposes a stalled uncaptured LSU offer")
        when(credit.io.reserve.valid) {
            assert(precheckedLoad && !lsu.io.start.bits.store && !lsu.io.start.bits.atomic &&
                !lsu.io.start.bits.forward.valid && pendingStoreRelied.orR && pendingStoreNewOfferAllowed &&
                !blockedByStore && !ledger.io.recoveryAccepted,
                (if (p.pendingReadyStoreBypass)
                    "one new early load reserves exact disjoint proofs under the pending-store readiness/head policy"
                 else "one new early load reserves exact disjoint store proofs while every relied store lacks data"))
        }
    }
    canonicalStoreTracker.foreach { tracker =>
        val epoch = lsu.io.start.bits.canonicalStoreEpoch.get
        epoch.valid := memoryChoice.valid && ledger.io.headValid && !ledger.io.headDone && pending(head) &&
            memoryChoice.index === head && memoryEntry.renamed.token.asUInt === headRenamed.token.asUInt &&
            virtualized && memoryEntry.request.memory && memoryEntry.request.store && !memoryEntry.request.atomic &&
            !memoryEntry.request.system && !memoryEntry.request.mulDiv &&
            AlignedMemoryDisjoint.aligned(address, memorySize) && io.loadPrecheck.get.stable &&
            !contextMemoryEpoch && !reserveSystem && !interruptDrain && !ledger.io.recovering
        epoch.bits := io.loadPrecheck.get.epoch
        tracker.io.start.valid := lsu.io.start.fire && epoch.valid
        tracker.io.start.bits.origin.token := lsu.io.start.bits.token
        tracker.io.start.bits.origin.epoch := epoch.bits
        tracker.io.start.bits.virtualAddress := address
        tracker.io.start.bits.size := memorySize
        tracker.io.start.bits.mask := byteLanes(memorySize, address)
        when(tracker.io.start.valid) {
            assert(!ledger.io.recoveryAccepted && !memoryProtected && !speculative && !postedBusy,
                "canonical tracking starts only for an accepted unprotected ordinary virtual head store")
        }
        when(lsu.io.start.fire && precheckedLoad && !frontierChoice && memoryChoice.index =/= head) {
            for (i <- 0 until p.robEntries) {
                when(memoryLive(i) && issueEntries(i).request.store && ages(i) < memoryChoice.age) {
                    assert((certFor(i) && AlignedMemoryDisjoint.withLanes(canonicalAddress, loadAligned, loadMask,
                        tracker.io.certificate.bits.physicalAddress(63, 3), tracker.io.certificate.bits.mask)) ||
                        (if (p.pendingReadyStoreBypass)
                            pendingStoreBypass && pendingStoreOfferAllowedFor.get(i) && pendingStoreDisjointFor(i)
                         else pendingStoreBypass && pendingStoreProofFor(i) && pendingStoreDisjointFor(i) &&
                            !pendingStoreDataReady(i)),
                        "every older store needs exact checked ownership or a retained pending write proof and disjoint PA bytes")
                }
            }
        }
    }
    lsu.io.start.bits.postedProof.foreach { proof =>
        proof := 0.U.asTypeOf(proof)
        proof.valid := postedEligible
        proof.bits.token.index := lsu.io.start.bits.token.index
        proof.bits.token.tag := lsu.io.start.bits.token.tag
        proof.bits.epoch := io.posted.get.contextEpoch
        proof.bits.address := lsu.io.start.bits.address
        proof.bits.data := lsu.io.start.bits.data << Cat(address(2, 0), 0.U(3.W))
        proof.bits.size := lsu.io.start.bits.size
        proof.bits.mask := byteLanes(memorySize, address)
        proof.bits.headAuthorized := true.B
        proof.bits.physicalPmpAllowed := true.B
        proof.bits.originalPhysical := true.B
        proof.bits.integerOrigin := true.B
        postedStarted := (lsu.io.start.fire && proof.valid) || directStoreFire
        when(lsu.io.start.fire && proof.valid) {
            assert(ledger.io.headValid && !ledger.io.headDone && pending(head) &&
                lsu.io.start.bits.token.asUInt === headRenamed.token.asUInt &&
                !pmpCheck.io.denied && !virtualized && !ledger.io.recoveryAccepted,
                "posted authority is captured only at the actual successful physical integer ROB-head start")
        }
        when(lsu.io.start.fire && !proof.valid) { assert(!postedBusy) }
        if (p.postedPrefetchHeadOffer) {
            when(postedStarted && !postedBusy) {
                assert(lsu.io.start.fire && proof.valid && !directStoreFire,
                    "PF head offer only relaxes the staged proof-bearing start")
                assert(!cpuAcceptedMemoryBusy.get,
                    "first posted head offer must drain integer, FP and posted accepted ownership")
                when(io.memoryBusy) {
                    assert(io.externalPrefetchBusy.get,
                        "only autonomous PF may remain busy at the first posted head offer")
                }
            }
        } else {
            when(postedStarted && !postedBusy) { assert(!io.memoryBusy) }
        }
    }
    // Guaranteed RAM writes receive a local StoreBuffer acknowledgement with request acceptance.
    // Retire only the current head and only after that acceptance; the LSU discards its duplicate
    // registered completion. MMIO, atomics, faults and backpressured writes keep the normal path.
    val fastStoreRetire = if (p.fastBufferedStoreRetire) lsu.io.start.fire &&
        memoryChoice.index === head && memoryEntry.request.store && !memoryEntry.request.atomic &&
        ordinaryRam && !pmpCheck.io.denied && lsu.io.memory.request.fire &&
        lsu.io.memory.response.fire && !lsu.io.memory.response.bits.error &&
        !lsu.io.memory.response.bits.pageFault else false.B
    val fastLoadRetire = if (p.fastHeadLoadRetire) lsu.io.fastLoadPreview.valid &&
        ledger.io.headValid && headRequest.memory && !headRequest.store && !headRequest.atomic &&
        lsu.io.fastLoadPreview.bits.token.asUInt === headRenamed.token.asUInt &&
        !memoryProtected && !ledger.io.recovering && !ledger.io.recoveryAccepted &&
        !ledger.io.headException.valid && io.commitEnable else false.B
    lsu.io.fastStoreRetire := fastStoreRetire
    lsu.io.fastLoadRetire := fastLoadRetire
    // Invalid fast-retire payload must not leave a dormant LSU-to-commit graph path.
    ledger.io.fastHeadRetire := 0.U.asTypeOf(ledger.io.fastHeadRetire)
    if (p.fastBufferedStoreRetire || p.fastHeadLoadRetire) {
        val fastStoreCompletion = Wire(new BackendCompletion(p))
        fastStoreCompletion := 0.U.asTypeOf(new BackendCompletion(p))
        fastStoreCompletion.token := Mux(directStoreFire, headRenamed.token, memoryEntry.renamed.token)
        fastStoreCompletion.nextPc := Mux(directStoreFire, headRequest.rename.pc +
            Mux(p.compressedInstructions.B && headRequest.rename.instruction(1, 0) =/= 3.U, 2.U, 4.U),
            memoryEntry.request.rename.pc +
                Mux(p.compressedInstructions.B && memoryEntry.request.rename.instruction(1, 0) =/= 3.U, 2.U, 4.U))
        ledger.io.fastHeadRetire.valid := directStoreFire || fastStoreRetire || fastLoadRetire
        ledger.io.fastHeadRetire.bits := Mux(fastLoadRetire, lsu.io.fastLoadPreview.bits, fastStoreCompletion)
    }
    for (slot <- 0 until p.memoryEntries) {
        lsu.io.cancel(slot) := lsu.io.live(slot) && killed(Mux(lsu.io.live(slot), lsu.io.owner(slot).index, 0.U))
    }
    val actualCanonicalAddress = proofFrontier.map(f => Mux(frontierChoice,
        f.io.frontier.bits.payload.physicalAddress, canonicalAddress)).getOrElse(canonicalAddress)
    val actualLanes = proofFrontier.map(f => Mux(frontierChoice,
        f.io.frontier.bits.payload.mask, selectedLanes)).getOrElse(selectedLanes)
    orderCheckValid := lsu.io.start.fire && (speculative || frontierChoice)
    when(lsu.io.start.fire) {
        when(precheckedLoad && !frontierChoice) {
            assert(preparedLoadMatches && (memoryChoice.index === head || !olderUncanonicalMemory),
                "a prechecked start requires its unchanged full-token certificate and canonical older memory")
        }
        pending(actualMemoryIndex) := false.B
        memoryCanonical.foreach(_(actualMemoryIndex) := !virtualized || precheckedLoad || frontierChoice)
        if (p.sharedMemoryAddressState) {
            // The old load-only bank was written on EVERY LSU start. Its values
            // for stores/atomics were never eligible for replay. Do not let those
            // starts overwrite a live store's prepared VA with a canonical PA.
            // Final LSU class includes the independent frontier-selected winner.
            when(sharedAddressLoadWrite.get) {
                storeAddress(actualMemoryIndex) := Cat(actualCanonicalAddress(63, 3), 0.U(3.W))
                storeByteLanes(actualMemoryIndex) := actualLanes
            }
        } else {
            loadBeat(actualMemoryIndex) := actualCanonicalAddress(63, 3)
            loadLanes(actualMemoryIndex) := actualLanes
        }
        orderCheckIndex := actualMemoryIndex
        orderCheckTag.foreach(_ := lsu.io.start.bits.token.tag)
        orderCheckBeat := actualCanonicalAddress(63, 3)
        orderCheckLanes := actualLanes
        // An overlapping RAM start must not release the previous irrevocable owner's protection.
        when(!speculative && !frontierChoice) {
            memoryProtected := true.B
            memoryOwner := lsu.io.start.bits.token
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
    proofFrontier.foreach { f =>
        when(frontierChoice) {
            val proof = f.io.frontier.bits
            lsu.io.start.bits.token := proof.token
            lsu.io.start.bits.address := proof.payload.address
            lsu.io.start.bits.physicalAddress := proof.payload.physicalAddress
            lsu.io.start.bits.translationEpoch := proof.epoch
            lsu.io.start.bits.precheckedLoad := true.B
            lsu.io.start.bits.forward.valid := false.B
            lsu.io.start.bits.store := false.B
            lsu.io.start.bits.atomic := false.B
            lsu.io.start.bits.size := proof.payload.size(1, 0)
            lsu.io.start.bits.unsigned := actualMemoryEntry.request.memoryUnsigned
            lsu.io.start.bits.accessDenied := false.B
            lsu.io.start.bits.canonicalStoreEpoch.get.valid := false.B
            lsu.io.start.bits.postedProof.foreach(_.valid := false.B)
            lsu.io.issueDestination.foreach { d =>
                d.valid := actualMemoryEntry.renamed.writesRd
                d.bits := actualMemoryEntry.renamed.destination
            }
        }
        when(lsu.io.start.fire) {
            assert(actualMemoryEntry.renamed.token.asUInt === lsu.io.start.bits.token.asUInt &&
                pending(actualMemoryIndex) && !proofOwnerClear(actualMemoryIndex),
                "every start revalidates the independently captured full owner token")
        }
        assert(!lsu.io.start.valid || lsu.io.start.ready,
            "frontier integration requires unconditional completion and no externally stalled start")
        val lineValid = RegInit(VecInit(Seq.fill(p.memoryEntries)(false.B)))
        val lines = Reg(Vec(p.memoryEntries, new MemoryProofLine(p)))
        for (slot <- 0 until p.memoryEntries) {
            f.io.liveLines(slot).valid := lineValid(slot) && lsu.io.live(slot) &&
                lines(slot).token.asUInt === lsu.io.owner(slot).asUInt
            f.io.liveLines(slot).bits := lines(slot)
            when(!lsu.io.live(slot)) { lineValid(slot) := false.B }
            when(lsu.io.acceptedStartSlot.get.valid && lsu.io.acceptedStartSlot.get.bits === slot.U) {
                lineValid(slot) := lsu.io.start.bits.precheckedLoad && !lsu.io.start.bits.store && !lsu.io.start.bits.atomic
                lines(slot).token := lsu.io.start.bits.token
                lines(slot).line := lsu.io.start.bits.physicalAddress(63, 6)
            }
        }
    }
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
            operands.io.source1(slot) := issueEntries(slot).renamed.source1
            operands.io.source2(slot) := issueEntries(slot).renamed.source2
        }
        for (kind <- 0 until 2) {
            selector.io.eligible(kind) := VecInit((0 until p.robEntries).map { i =>
                val source1 = Mux(pending(i), issueEntries(i).renamed.source1, 0.U)
                val source2 = Mux(pending(i), issueEntries(i).renamed.source2, 0.U)
                pending(i) && issueEntries(i).request.mulDiv && issueEntries(i).request.mulDivOp(2) === (kind == 1).B &&
                    ownerReady.map(_.io.ready1(i)).getOrElse(operandReady(source1)) &&
                    ownerReady.map(_.io.ready2(i)).getOrElse(operandReady(source2))
            }).asUInt
            val entry = readIssue(selector.io.index(kind), s"mulDiv$kind", Set("pc"),
                Some(selector.io.owner(kind)))
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
            c.valid := pending(i) && issueEntries(i).request.mulDiv &&
                Mux(issueEntries(i).request.mulDivOp(2), mulDiv.io.start.ready, multiplier.io.start.ready) &&
                operandReady(Mux(pending(i), issueEntries(i).renamed.source1, 0.U)) &&
                operandReady(Mux(pending(i), issueEntries(i).renamed.source2, 0.U))
            c.index := i.U
            c.age   := ages(i)
            c
        })
        val entry = readIssue(mulDivChoice.index, "mulDiv", Set("pc"))
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

    if (p.shareProtectedHeadPayload) {
        // System/FP starts only at the current head. Its protected lifetime ends
        // exactly at retirement or accepted exceptional completion; neither a
        // younger redirect nor held retirement may change this full-token owner.
        when(systemProtected) {
            assert(ledger.io.headValid && ledger.io.headSystem.get.headToken.asUInt === systemOwner.asUInt &&
                headRenamed.token.asUInt === systemOwner.asUInt,
                "protected system payload owner must remain the exact ROB and queue head")
        }
        when(systemComplete.valid) {
            assert(systemProtected && systemComplete.bits.token.asUInt === systemOwner.asUInt,
                "held or exceptional system completion must retain the protected full token")
        }
    }
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
        io.pmpRawChanged.foreach(_ := unit.io.pmpRawChanged.get)
        io.fetchPrivilege.get := unit.io.fetchPrivilege
        io.imsic.get <> unit.io.imsic
        unit.io.externalInterrupt           := io.externalInterrupt.get
        unit.io.supervisorExternalInterrupt := io.supervisorExternalInterrupt.get
        unit.io.timerInterrupt              := io.timerInterrupt.get
        unit.io.timeValue                   := io.timeValue.get
        io.fenceIFlush.get := unit.io.fenceIFlush
        unit.io.fenceIFlushReady := io.fenceIFlushReady.get
        interruptDrain                      := unit.io.interruptPending && !systemProtected
        val headPending = pending(head) && issueEntries(head).request.system
        val headInst = Mux(p.compressedInstructions.B &&
            headRequest.rename.instruction(1, 0) =/= 3.U,
            headRequest.expandedInstruction, headRequest.rename.instruction)
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
        val drainFetch = if (p.predecodedHeadDrain) headPending && headDrainClasses.get(head)
            else pmpHead || returnHead || vmHead || fenceIHead
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
        val source      = Mux(headPending, issueEntries(head).renamed.source1, 0.U)
        reserveSystem := !unit.io.interruptPending && headPending && ready(
            source
        ) && unit.io.start.ready && io.commitEnable &&
            !io.memoryBusy && !ledger.io.recovering &&
            (if (p.pmpEntries > 0) !drainFetch || io.fetchQuiescent.get else true.B)
        unit.io.start.valid      := reserveSystem && !ledger.io.recoveryAccepted && !ledger.io.pendingException.valid
        unit.io.start.bits.token := issueEntries(head).renamed.token
        unit.io.start.bits.pc    := headRequest.rename.pc
        unit.io.start.bits.instruction := headInst
        unit.io.start.bits.operand     := readPhysical(source)
        systemStart                    := unit.io.start.fire
        when(unit.io.start.fire) {
            systemFpMemory.foreach(_ := FloatingPointSubset.memory(headInst))
            systemContextBarrier := !(p.fpEnabled.B && FloatingPointDecode.supported(headInst, p.fpConfig) &&
                !FloatingPointDecode.memory(headInst))
            pending(head)   := false.B
            systemProtected := true.B
            systemOwner     := issueEntries(head).renamed.token
        }
        systemComplete.valid   := unit.io.complete.valid
        systemComplete.bits    := unit.io.complete.bits.completion
        // Compressed FP memory uses the expanded encoding for execution, but
        // sequential retirement must retain the original two-byte instruction.
        if (p.compressedInstructions && p.fpEnabled) {
            val owner = if (p.shareProtectedHeadPayload) headRequest
                else readIssue(systemOwner.index, "systemCompletion", ImmutableIssuePayload.head).request
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
    val executionRetirementOffer = if (p.retirementIntent)
        Some(Wire(Vec(p.completionWidth, Bool()))) else None
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
        // Retain the old full queue-token read only as an independent witness on lane 1.
        // Both rows are written from the same accepted rename token; retire/recovery
        // leave their payloads intact. A pure ROB tag match therefore preserves stale
        // semantics even outside the live window. Lane 0 has other completion producers.
        val queueOwnerMatches = issueEntries(ownerIndex).renamed.token.asUInt === entry.renamed.token.asUInt
        val ownerMatches = if (p.sharedLane1OwnerMatch && lane == 1) ledger.io.lane1OwnerMatch.get
        else queueOwnerMatches
        val stale = !ownerMatches
        if (p.sharedLane1OwnerMatch && lane == 1) {
            when(stage.io.occupied) {
                assert(queueOwnerMatches === ownerMatches,
                    "lane-1 pure ROB tag equality must match the independent full queue-token witness")
                assert(ledger.io.complete(1).bits.token.asUInt === entry.renamed.token.asUInt,
                    "lane-1 owner query must use the raw held execution token independently of completion valid")
            }
        }
        stage.io.cancel := stage.io.occupied && (killed(ownerIndex) || stale)
        stage.io.deq.ready := (if (lane == 0) branchResultPortFree else true.B) &&
            (!branchRedirectValid || entry.request.controlFlow === ControlFlow.none)
        executionRetirementOffer.foreach(_(lane) := stage.io.occupied && ownerMatches && stage.io.deq.ready)
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
    systemCandidate.pc := headRequest.rename.pc
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
                issueEntries(head).renamed.token.asUInt === systemOwner.asUInt,
                "system completion, protected owner and current ROB/queue head must have the same full token")
            assert(!ledger.io.recoveryProbe.valid && !automaticTrap,
                "system protection excludes external recovery and automatic traps until precise completion/retirement")
        }
    } else {
        val systemRedirectPc = readIssue(systemComplete.bits.token.index, "systemRedirect", Set("pc"))
            .request.rename.pc
        when(systemComplete.valid && systemRedirect) {
            branchCandidate.valid       := true.B
            branchCandidate.bits.token  := systemComplete.bits.token
            branchCandidate.bits.pc     := systemRedirectPc
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
        val selectedBranch = if (p.retirementIntent)
            executionRetirementOffer.get(lane) &&
                executingOperands(lane).entry.request.controlFlow =/= ControlFlow.none
        else selected(lane).valid && issueEntries(selected(lane).bits).request.controlFlow =/= ControlFlow.none
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
            eligible(i) && (!branchRedirectValid || issueEntries(i).request.controlFlow === ControlFlow.none))).asUInt
    }
    val physicalOperands = if (p.oneHotPhysicalOperands) Some(independentPhysicalOperands()) else None
    physicalOperands.foreach { operands =>
        operands.io.owners(0) := issueSelector.get.io.second
        operands.io.owners(1) := issueSelector.get.io.first
        if (!p.lvtPhysicalRegisterFile) operands.io.values := values.get
        for (slot <- 0 until p.robEntries) {
            operands.io.source1(slot) := issueEntries(slot).renamed.source1
            operands.io.source2(slot) := issueEntries(slot).renamed.source2
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
            val entry = issueEntries(slot)
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
            operands.io.source1(slot) := issueEntries(slot).renamed.source1
            operands.io.source2(slot) := issueEntries(slot).renamed.source2
        }
        val dataReady = VecInit((0 until p.robEntries).map(i =>
            ownerReady.map(_.io.ready2(i)).getOrElse(
                operandReady(Mux(pending(i), issueEntries(i).renamed.source2, 0.U))))).asUInt
        val payloads = Wire(Vec(2, new EarlyStoreOperands))
        for (rank <- 0 until 2) {
            val index = if (rank == 0) stores.io.firstIndex else stores.io.secondIndex
            val entry = readIssue(index, s"storePreparation$rank", Set("immediate"), Some(owners(rank)))
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
            issueEntries(i).request.controlFlow === ControlFlow.none)
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
            issueEntries(i).request.controlFlow === ControlFlow.none) &&
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
                !branchRedirectValid || ((lane > 0).B && issueEntries(i).request.controlFlow === ControlFlow.none)
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
                        owner(i) -> (issueEntries(i).request.memory && issueEntries(i).request.store)))
                } else {
                    val rank = if (lane == 0) rankedSecond else rankedFirst
                    issueEntries(rank.index).request.memory && issueEntries(rank.index).request.store
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
            readIssue(dispatchChoice.index, s"execution$lane", ImmutableIssuePayload.execution, Some(oneHot))
        } else readIssue(dispatchChoice.index, s"execution$lane", ImmutableIssuePayload.execution)
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
                operandReady(Mux(pending(i), issueEntries(i).renamed.source2, 0.U))))).asUInt
            payloads(lane).dataReady := (owner & dataReady).orR
        }
        val dispatchStore = dispatchEntry.request.memory && dispatchEntry.request.store
        val preparationGrant = if (p.registeredIssueExecute) issueOpportunity else dispatchChoice.valid
        prepared(lane) := preparationGrant && dispatchStore && !killed(dispatchChoice.index) &&
            !ledger.io.headException.valid
        preparedOwners(lane) := Mux(prepared(lane), UIntToOH(dispatchChoice.index, p.robEntries), 0.U)
        if (!p.earlyStorePreparation) {
            when(prepared(lane)) {
                sharedAddressStoreWrites.foreach(_(dispatchChoice.index)(lane) := true.B)
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
            // Eligible memory entries are stores; enqueue excludes those stores.
            // Thus every valid offer is non-memory. Keep the shared dispatch and
            // store-preparation operands unchanged, including invalid held state.
            incoming.left := (if (p.directRegisteredExecutionOperands) issueOperandValue(source1, storedLeft)
                else dispatchLeft)
            incoming.right := (if (p.directRegisteredExecutionOperands) issueOperandValue(source2, storedRight)
                else dispatchRight)
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
            if (p.registeredLoadResultReady) {
                for ((source, used, value) <- Seq(
                    (source1, !dispatchEntry.request.usePc, incoming.left),
                    (source2, !dispatchEntry.request.useImmediate, incoming.right))) {
                    val hits = lsu.io.heldLoadValue.get.map(h => h.valid && h.bits.destination === source)
                    when(stage.io.enq.fire && used && hits.reduce(_ || _)) {
                        assert(PopCount(hits) === 1.U,
                            "a captured source must name one successful held load")
                        for (slot <- 0 until p.memoryEntries) {
                            val holder = lsu.io.heldLoadValue.get(slot)
                            val token = lsu.io.owner(slot)
                            val index = Mux(hits(slot), token.index, 0.U)
                            when(hits(slot)) {
                                assert(!killed(index) && !killed(dispatchChoice.index) &&
                                    value === holder.bits.data,
                                    "captured held-load source must survive recovery and preserve its exact old data")
                                when(lsu.io.complete.valid && lsu.io.complete.bits.token.asUInt === token.asUInt) {
                                    assert(ledger.io.completionAccepted(0) &&
                                        !ledger.io.complete(0).bits.exception,
                                        "a selected held-load producer captured this edge must actually complete")
                                }
                            }
                        }
                    }
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
            // The opt-in lane-0 promise describes its stable OLD ordinary-ALU value,
            // including a writeback-port stall. It never consumes/replaces that owner
            // or authorizes ROB/PRF effects. Current consumer kill remains at enq.
            // Lane 1 and the default-OFF expression remain the original contract.
            executionWake(lane).valid := (if (p.heldAluIssueForwarding && lane == 0)
                stage.io.occupied && executingOperands(lane).forwardable
            else stage.io.occupied && stage.io.deq.ready && executingOperands(lane).forwardable)
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
        // This is an offer, not permission to retire: branch and fault offers
        // still suppress duplicate lanes. Existing class/fault inputs qualify
        // retirement independently. No completion or writeback uses this bit.
        ledger.io.retirementIntentValid.foreach(_(lane) := executionRetirementOffer.get(lane) && !prepareStore)
        if (lane == 0) {
            if (p.registeredBranchRedirect && !p.precompleteMispredictedBranch) {
                when(branchRedirectReady) {
                    ledger.io.complete(lane).valid :=
                        branchRedirectMatches
                    ledger.io.retirementIntentValid.foreach(_(lane) := branchRedirectMatches)
                    if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := branchResult }
                    retireFault := branchResult.exception
                }
            }
            when(systemComplete.valid) {
                ledger.io.complete(lane).valid := !systemRedirect || systemRedirectMatches
                ledger.io.retirementIntentValid.foreach(_(lane) := !systemRedirect || systemRedirectMatches)
                if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := systemComplete.bits }
                retireFault := systemComplete.bits.exception
            }
            when(multiplier.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                ledger.io.retirementIntentValid.foreach(_(lane) := true.B)
                if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := multiplier.io.complete.bits }
                retireFault := multiplier.io.complete.bits.exception
            }
            when(mulDiv.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                ledger.io.retirementIntentValid.foreach(_(lane) := true.B)
                if (!p.parallelCompletionPayload) { ledger.io.complete(lane).bits := mulDiv.io.complete.bits }
                retireFault := mulDiv.io.complete.bits.exception
            }
            when(lsu.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                ledger.io.retirementIntentValid.foreach(_(lane) := true.B)
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
        val completedEntry = issueEntries(completedIndex)
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
                assert(payloads(rank).token.asUInt === issueEntries(slot).renamed.token.asUInt,
                    "early store payload must match the final granted owner token")
            }
            val operand = captured(rank)
            val liveOwner = pending(slot) && memoryLive(slot) && !killed(slot) &&
                issueEntries(slot).renamed.token.asUInt === operand.token.asUInt
            when(capturedOwners(rank)(slot) && liveOwner) {
                sharedAddressStoreWrites.foreach(_(slot)(rank) := true.B)
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
    sharedAddressStoreWrites.foreach { writers =>
        for (slot <- 0 until p.robEntries) {
            assert(PopCount(writers(slot)) <= 1.U,
                "independent store preparation ranks cannot write the same address row")
            when(writers(slot).asUInt.orR) {
                assert(issueEntries(slot).request.memory && issueEntries(slot).request.store,
                    "a prepared address write must retain the current store interpretation")
            }
            when(sharedAddressLoadWrite.get && actualMemoryIndex === slot.U) {
                assert(!writers(slot).asUInt.orR,
                    "ordinary load and prepared stores may write concurrently only at different rows")
                assert(issueEntries(slot).request.memory && !issueEntries(slot).request.store &&
                    !issueEntries(slot).request.atomic,
                    "replay bounds belong only to the actual accepted ordinary load")
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
            if (p.residentMemoryPayloadReuse) {
                val offered = io.allocate(lane).bits
                when(offered.memory && !offered.store && !offered.atomic) {
                    assert(offered.rename.rs2 === 0.U && renamed.bits.source2 === 0.U,
                        "resident reuse rejects accepted noncanonical ordinary-load source2")
                }
            }
            queue(renamed.bits.token.index).renamed := renamed.bits
            if (p.reconstructIssueTokenIndex) {
                // Like the banked immutable payload below, this unused field is
                // tied to a constant at its only writer and removed by lowering.
                queue(renamed.bits.token.index).renamed.token.index := 0.U
            }
            queue(renamed.bits.token.index).request := io.allocate(lane).bits
            headDrainClasses.foreach { classes =>
                val offered = io.allocate(lane).bits
                classes(renamed.bits.token.index) := HeadDrainClass(
                    offered.rename.instruction, offered.expandedInstruction, p)
            }
            if (p.bankedIssuePayload) {
                ImmutableIssuePayload.insert(queue(renamed.bits.token.index).request,
                    0.U.asTypeOf(new ImmutableIssuePayload))
            }
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
    if (p.registeredLoadResultReady) {
        for (slot <- 0 until p.memoryEntries) {
            val holder = lsu.io.heldLoadValue.get(slot)
            val token = lsu.io.owner(slot)
            val draining = holder.valid && lsu.io.complete.fire &&
                lsu.io.complete.bits.token.asUInt === token.asUInt
            val oldDependants = (0 until p.robEntries).map { row =>
                val entry = issueEntries(row)
                val overwritten = ledger.io.renamed.map(r => r.valid && r.bits.token.index === row.U).reduce(_ || _)
                val captured = (0 until p.completionWidth).map(lane => executionEnqueued(lane) &&
                    dispatched(lane).bits === row.U).reduce(_ || _)
                val completed = (0 until p.completionWidth).map(lane => ledger.io.completionAccepted(lane) &&
                    ledger.io.complete(lane).bits.token.asUInt === entry.renamed.token.asUInt).reduce(_ || _)
                pending(row) && executionReadyClass(entry.request) && !killed(row) && !overwritten &&
                    !captured && !completed && (entry.renamed.source1 === holder.bits.destination ||
                        entry.renamed.source2 === holder.bits.destination)
            }.reduce(_ || _)
            val newDependants = (0 until p.renameWidth).map { lane =>
                val renamed = ledger.io.renamed(lane)
                renamed.valid && executionReadyClass(io.allocate(lane).bits) &&
                    (renamed.bits.source1 === holder.bits.destination || renamed.bits.source2 === holder.bits.destination)
            }.reduce(_ || _)
            val capturingDependants = (0 until p.completionWidth).map { lane =>
                val incoming = executionStages(lane).io.enq.bits.asTypeOf(new IntegerExecutionOperands(p))
                executionEnqueued(lane) &&
                    ((!incoming.entry.request.usePc && incoming.entry.renamed.source1 === holder.bits.destination) ||
                        (!incoming.entry.request.useImmediate && incoming.entry.renamed.source2 === holder.bits.destination))
            }.reduce(_ || _)
            val reserved = readyUpdate.get.io.reserve.map(r =>
                r.valid && r.bits === holder.bits.destination).reduce(_ || _)
            when(draining && (oldDependants || newDependants || capturingDependants)) {
                assert(ledger.io.completionAccepted(0) && !ledger.io.complete(0).bits.exception &&
                    ledger.io.complete(0).bits.token.asUInt === token.asUInt &&
                    physicalWrites.get(0).valid && physicalWrites.get(0).bits.address === holder.bits.destination &&
                    physicalWrites.get(0).bits.data === holder.bits.data &&
                    readyUpdate.get.io.wake(0).valid && readyUpdate.get.io.wake(0).bits === holder.bits.destination &&
                    !reserved,
                    "a drained held load needed by the next pending population must atomically write its exact PRF value")
            }
        }
    }
    if (p.bankedIssuePayload) {
        val payload = Module(new BankedIssuePayload(p.robEntries, issuePayloadReads.map(_._4).toSeq))
        for (lane <- 0 until p.renameWidth) {
            payload.io.write(lane).valid := ledger.io.renamed(lane).valid
            payload.io.write(lane).bits.index := ledger.io.renamed(lane).bits.token.index
            payload.io.write(lane).bits.data := ImmutableIssuePayload.fromRequest(io.allocate(lane).bits)
        }
        for (((_, index, enable, _, data), port) <- issuePayloadReads.zipWithIndex) {
            payload.io.address(port) := index
            payload.io.enable(port) := enable
            data := payload.io.data(port)
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
