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
  * tournaments. PRF muxes, selection, ALU and writeback form an unpipelined path; frequency/area are unverified and
  * wider configurations require a separate physical design assessment. Initial architectural registers are zero for
  * this standalone bring-up interface, not an ISA reset claim.
  */
class IntegerBackend(val p: OooParams = OooParams()) extends Module {
    val io = IO(new Bundle {
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
        val memoryBusy                  = Output(Bool())
        val issueCount                  = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val memoryDiscarded             = Output(Bool())
        val memoryForwarded             = Output(Bool())
        val mulDivCancelled             = Output(Bool())
        val mulDivOverlap               = Output(Bool())
        val mulDivBlocked               = Output(Bool())
        val mulDivConcurrent            = Output(Bool())
        val mulDivMultiCancel           = Output(Bool())
    })
    val ledger          = Module(new RenameRob(p))
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
    val systemOwner     = RegInit(0.U.asTypeOf(new RobToken(p)))
    val automaticTrap   = WireDefault(false.B)
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
    io.memoryBusy      := lsu.io.busy
    io.memoryDiscarded := lsu.io.discarded
    io.memoryForwarded := lsu.io.forwarded
    val storeBufferStallCause = WireDefault(0.U(3.W))
    val fastStoreReady = WireDefault(false.B)
    val fastStoreRequest = WireDefault(0.U.asTypeOf(new DataRequest))
    val fastStoreValid = WireDefault(false.B)
    if (p.bufferedRamStores) {
        val stores = Module(new StoreBuffer(p))
        stores.io.upstream <> lsu.io.memory
        stores.io.fastStore.valid := fastStoreValid
        stores.io.fastStore.bits := fastStoreRequest
        fastStoreReady := stores.io.fastStore.ready
        io.memory <> stores.io.memory
        io.memoryBusy      := lsu.io.busy || stores.io.busy
        io.memoryForwarded := lsu.io.forwarded || stores.io.forwarded
        storeBufferStallCause := stores.io.requestStallCause
    } else {
        io.memory <> lsu.io.memory
    }
    for (lane <- 0 until p.renameWidth) {
        ledger.io.allocate(lane).valid := io.allocate(lane).valid
        ledger.io.allocate(lane).bits  := io.allocate(lane).bits.rename
    }
    ledger.io.dispatchReady       := !emptyTrap // One reservation slot per ROB entry guarantees capacity.
    ledger.io.commitEnable        := io.commitEnable
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

    val values        = RegInit(VecInit(Seq.fill(p.physicalRegs)(0.U(64.W))))
    val ready         = RegInit(VecInit((0 until p.physicalRegs).map(i => (i < 32).B)))
    val pending       = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val memoryLive    = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val storeAddressKnown = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val storePrepared = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val storeAddress  = Reg(Vec(p.robEntries, UInt(64.W)))
    val storeData     = Reg(Vec(p.robEntries, UInt(64.W)))
    val loadBeat      = Reg(Vec(p.robEntries, UInt(61.W)))
    val loadLanes     = Reg(Vec(p.robEntries, UInt(8.W)))
    val orderCheckValid = RegInit(false.B)
    val orderCheckIndex = RegInit(0.U(p.robBits.W))
    val orderCheckBeat  = Reg(UInt(61.W))
    val orderCheckLanes = Reg(UInt(8.W))
    val queue         = Reg(Vec(p.robEntries, new IntegerIssueEntry(p)))
    io.committedValue := Mux(io.inspectRegister === 0.U, 0.U, values(ledger.io.committedMapping))

    // Recovery removes tails, so the head advances only on commit. Slot age needs robBits, not a full tag compare.
    val head = RegInit(0.U(p.robBits.W))
    head := head + PopCount(ledger.io.commit.map(_.valid))
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
    def operandReady(index: UInt): Bool = ready(index) ||
        (completedLoadBypass && index === completedLoadEntry.renamed.destination) ||
        (wordPreviewBypass && index === wordPreviewDestination)
    def operandValue(index: UInt): UInt = Mux(
        completedLoadBypass && index === completedLoadEntry.renamed.destination,
        lsu.io.complete.bits.data,
        Mux(wordPreviewBypass && index === wordPreviewDestination,
            multiplier.io.wordPreview.bits.data, values(index)))
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
        killed(i) := ledger.io.recoveryAccepted && (ages(i) > boundaryAge ||
            (ledger.io.recover.bits.inclusive && i.U === ledger.io.recover.bits.token.index))
        // Selection must not depend on its own branch resolution. Authorization below suppresses killed results.
        val prepareStore = entry.request.memory && entry.request.store && !storePrepared(i) && i.U =/= head
        val source1Ready = entry.request.usePc || operandReady(Mux(pending(i), entry.renamed.source1, 0.U))
        val source2Ready = entry.request.useImmediate || operandReady(Mux(pending(i), entry.renamed.source2, 0.U))
        eligible(i) := pending(
            i
        ) && !entry.request.system && !entry.request.mulDiv && (!entry.request.memory || prepareStore) &&
            source1Ready && (source2Ready || (prepareStore && !storeAddressKnown(i)))
        when(killed(i)) {
            pending(i) := false.B
            memoryLive(i) := false.B
            storeAddressKnown(i) := false.B
            storePrepared(i) := false.B
        }
        when(ledger.io.commit.map(c => c.valid && c.bits.token.index === i.U).reduce(_ || _)) {
            memoryLive(i)    := false.B
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
    val fastEnd = fastAddress +& (1.U(64.W) << fastSize)
    val fastAligned = (fastAddress(2, 0) & ((1.U << fastSize) - 1.U)) === 0.U
    val fastRam = if (p.speculativeRamBytes == 0) false.B else
        fastAddress >= p.speculativeRamBase.U(65.W) &&
            fastEnd <= (p.speculativeRamBase + p.speculativeRamBytes).U(65.W)
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
    val memoryChoice = tournament((0 until p.robEntries).map { i =>
        val c            = Wire(new Candidate)
        val entry        = queue(i)
        val sourcesReady = operandReady(entry.renamed.source1) &&
            (!(entry.request.store || entry.request.atomic) || operandReady(entry.renamed.source2))
        c.valid := pending(i) && entry.request.memory && (!entry.request.store || i.U === head) &&
            !(directStoreReserve && i.U === head) &&
            (storePrepared(i) || sourcesReady)
        c.index := i.U
        c.age   := ages(i)
        c
    })
    val memoryEntry   = queue(memoryChoice.index)
    val memorySize    = Mux(memoryChoice.valid, memoryEntry.request.memorySize, 0.U)
    val memorySource1 = Mux(memoryChoice.valid, memoryEntry.renamed.source1, 0.U)
    val memorySource2 = Mux(memoryChoice.valid, memoryEntry.renamed.source2, 0.U)
    val savedStore    = memoryChoice.valid && memoryEntry.request.store && storePrepared(memoryChoice.index)
    val address       =
        Mux(savedStore, storeAddress(memoryChoice.index), operandValue(memorySource1) + memoryEntry.request.immediate)
    val pmpCheck = Module(new PmpChecker(p.pmpEntries))
    pmpCheck.io.state     := pmpState
    pmpCheck.io.address   := address
    pmpCheck.io.size      := memorySize
    pmpCheck.io.privilege := dataPrivilege
    pmpCheck.io.access    := Mux(memoryEntry.request.atomic,
        Mux(memoryEntry.request.atomicOp === 2.U, PmpAccess.read,
            Mux(memoryEntry.request.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
        Mux(memoryEntry.request.store, PmpAccess.write, PmpAccess.read))
    val accessEnd   = address +& (1.U(64.W) << memorySize)
    val ordinaryRam =
        if (p.speculativeRamBytes == 0) false.B
        else
            !virtualized && address >= p.speculativeRamBase.U(65.W) &&
            accessEnd <= (p.speculativeRamBase + p.speculativeRamBytes).U(65.W)
    val sourceStore                                = lsu.io.forwardStore
    def byteLanes(size: UInt, address: UInt): UInt = {
        val mask = MuxLookup(size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
        (mask << address(2, 0))(7, 0)
    }
    val loadMask  = byteLanes(memorySize, address)
    val storeMask = byteLanes(sourceStore.bits.size, sourceStore.bits.address)
    val sourceEnd = sourceStore.bits.address +& (1.U(64.W) << sourceStore.bits.size)
    val sourceRam =
        if (p.speculativeRamBytes == 0) false.B
        else
            sourceStore.bits.address >= p.speculativeRamBase.U(65.W) &&
            sourceEnd <= (p.speculativeRamBase + p.speculativeRamBytes).U(65.W)
    val forwarding =
        sourceStore.valid && sourceRam && ordinaryRam && !memoryEntry.request.store && !memoryEntry.request.atomic &&
            sourceStore.bits.address(63, 3) === address(63, 3) && (storeMask & loadMask) === loadMask &&
            memoryLive(sourceStore.bits.token.index) &&
            (sourceStore.bits.token.index - head) < memoryChoice.age
    val blockedByStore = (0 until p.robEntries)
        .map { i =>
            val size    = Mux(storeAddressKnown(i), queue(i).request.memorySize, 0.U)
            val end     = storeAddress(i) +& (1.U(64.W) << size)
            val aligned = (storeAddress(i)(2, 0) & ((1.U << size) - 1.U)) === 0.U
            val ram     =
                if (p.speculativeRamBytes == 0) false.B
                else
                    storeAddress(i) >= p.speculativeRamBase.U(65.W) &&
                    end <= (p.speculativeRamBase + p.speculativeRamBytes).U(65.W)
            val disjoint = end <= address || accessEnd <= storeAddress(i)
            memoryLive(i) && queue(i).request.store && ages(i) < memoryChoice.age &&
            !(storeAddressKnown(i) && aligned && ram && disjoint) &&
            !(forwarding && queue(i).renamed.token.asUInt === sourceStore.bits.token.asUInt)
        }
        .reduce(_ || _)
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
        !interruptDrain && !reserveSystem && !olderSystem && memoryChoice.valid && lsu.io.issueAvailable && io.commitEnable &&
            ((p.issueWidth > 1).B || !directStoreReserve) &&
            !ledger.io.recovering && (!memoryEntry.request.atomic || !io.memoryBusy) &&
            (savedStore || (operandReady(
                memorySource1
            ) && (!(memoryEntry.request.store || memoryEntry.request.atomic) || operandReady(memorySource2)))) &&
            (memoryChoice.index === head || (speculative && !blockedByStore))
    val youngerLoadCouldIssue = !interruptDrain && !reserveSystem && !olderSystem && memoryChoice.valid &&
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
    val selectedLanes = byteLanes(memorySize, address)
    val checkedAge = orderCheckIndex - head
    val loadReplay = tournament((0 until p.robEntries).map { i =>
        val c       = Wire(new Candidate)
        val overlap = loadBeat(i) === orderCheckBeat && (loadLanes(i) & orderCheckLanes).orR
        // This check runs exactly one cycle after issue; the owner cannot retire and reuse its ROB slot yet.
        c.valid := orderCheckValid && memoryLive(orderCheckIndex) &&
            memoryLive(i) && !pending(i) && queue(i).request.memory &&
            !queue(i).request.store && !queue(i).request.atomic &&
            ages(i) > checkedAge && overlap
        c.index := i.U
        c.age   := ages(i)
        c
    })
    lsu.io.start.valid              := reserveMemory && !ledger.io.recoveryAccepted && !ledger.io.headException.valid
    io.headProfile.storePrepared := ledger.io.headValid && headRequest.store && storePrepared(head)
    io.headProfile.memoryStarting := directStoreFire || (lsu.io.start.fire && memoryChoice.index === head)
    io.headProfile.memorySlotAvailable := lsu.io.issueAvailable
    lsu.io.parallel                 := speculative
    lsu.io.start.bits.forward.valid := forwarding
    lsu.io.start.bits.forward.bits  := sourceStore.bits.data
    lsu.io.start.bits.token         := memoryEntry.renamed.token
    lsu.io.start.bits.pc            := memoryEntry.request.rename.pc
    lsu.io.start.bits.address       := address
    lsu.io.start.bits.data          := Mux(savedStore, storeData(memoryChoice.index), operandValue(memorySource2))
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
        pending(memoryChoice.index) := false.B
        loadBeat(memoryChoice.index)  := address(63, 3)
        loadLanes(memoryChoice.index) := selectedLanes
        orderCheckIndex := memoryChoice.index
        orderCheckBeat  := address(63, 3)
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
    lsu.io.complete.ready := ledger.io.completionAccepted(0)
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
    val mulDivChoice = tournament((0 until p.robEntries).map { i =>
        val c = Wire(new Candidate)
        c.valid := pending(i) && queue(i).request.mulDiv &&
            Mux(queue(i).request.mulDivOp(2), mulDiv.io.start.ready, multiplier.io.start.ready) &&
            operandReady(Mux(pending(i), queue(i).renamed.source1, 0.U)) &&
            operandReady(Mux(pending(i), queue(i).renamed.source2, 0.U))
        c.index := i.U
        c.age   := ages(i)
        c
    })
    val mulDivEntry   = queue(mulDivChoice.index)
    val reserveMulDiv = mulDivChoice.valid && !reserveSystem && !reserveMemory &&
        ((p.issueWidth > 1).B || !directStoreReserve) && !ledger.io.recovering
    val mStart        = reserveMulDiv && !ledger.io.recoveryAccepted && !ledger.io.headException.valid
    mulDiv.io.start.valid          := mStart && mulDivEntry.request.mulDivOp(2)
    multiplier.io.start.valid      := mStart && !mulDivEntry.request.mulDivOp(2)
    multiplier.io.start.bits       := mulDiv.io.start.bits
    mulDiv.io.start.bits.token     := mulDivEntry.renamed.token
    mulDiv.io.start.bits.pc        := mulDivEntry.request.rename.pc
    mulDiv.io.start.bits.operation := mulDivEntry.request.mulDivOp
    mulDiv.io.start.bits.word      := mulDivEntry.request.word
    mulDiv.io.start.bits.left      := operandValue(Mux(mulDivChoice.valid, mulDivEntry.renamed.source1, 0.U))
    mulDiv.io.start.bits.right     := operandValue(Mux(mulDivChoice.valid, mulDivEntry.renamed.source2, 0.U))
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
        unit.io.start.bits.operand     := values(source)
        systemStart                    := unit.io.start.fire
        when(unit.io.start.fire) {
            pending(head)   := false.B
            systemProtected := true.B
            systemOwner     := queue(head).renamed.token
        }
        systemComplete.valid   := unit.io.complete.valid
        systemComplete.bits    := unit.io.complete.bits.completion
        systemRedirect         := unit.io.complete.bits.redirect
        systemInvalidate       := unit.io.complete.valid && unit.io.complete.bits.invalidateFetch
        unit.io.complete.ready := systemComplete.ready
        val safeTrap = io.commitEnable && !io.memoryBusy && !systemProtected && !memoryProtected &&
            !ledger.io.recovering && unit.io.start.ready
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
        when(automaticTrap && !emptyTrap) {
            recovery.valid          := true.B
            recovery.bits.token     := trapEvent.token
            recovery.bits.inclusive := true.B
        }
        unit.io.trap.valid := automaticTrap && (io.recoveryAccepted || emptyTrap)
        unit.io.trap.bits  := trapEvent
        trapTarget         := unit.io.trapTarget
        io.trap.get        := unit.io.trap
    }
    val selected        = Wire(Vec(p.completionWidth, Valid(UInt(p.robBits.W))))
    val prepared        = Wire(Vec(p.completionWidth, Bool()))
    val resolutions     = Wire(Vec(p.completionWidth, Valid(new FrontendRedirect(p))))
    val completion      = Wire(Vec(p.completionWidth, new BackendCompletion(p)))
    val branchCandidate = Wire(Valid(new FrontendRedirect(p)))
    val localInclusive  = WireDefault(false.B)
    branchCandidate.valid := resolutions.map(_.valid).reduce(_ || _)
    // No branch means no token: keep an inactive candidate from indexing the ROB with undefined queue data.
    branchCandidate.bits := Mux(
        branchCandidate.valid,
        PriorityMux(resolutions.map(r => r.valid -> r.bits)),
        0.U.asTypeOf(new FrontendRedirect(p))
    )
    when(systemComplete.valid && systemRedirect) {
        branchCandidate.valid       := true.B
        branchCandidate.bits.token  := systemComplete.bits.token
        branchCandidate.bits.pc     := queue(systemComplete.bits.token.index).request.rename.pc
        branchCandidate.bits.target := systemComplete.bits.nextPc
    }
    val localCandidate = Wire(Valid(new FrontendRedirect(p)))
    localCandidate := branchCandidate
    when(loadReplay.valid && (!branchCandidate.valid ||
        loadReplay.age < (branchCandidate.bits.token.index - head))) {
        localCandidate.valid       := true.B
        localCandidate.bits.token  := queue(loadReplay.index).renamed.token
        localCandidate.bits.pc     := queue(loadReplay.index).request.rename.pc
        localCandidate.bits.target := queue(loadReplay.index).request.rename.pc
        localInclusive             := true.B
    }
    val externalWins = ledger.io.recoveryProbeAccepted && (!localCandidate.valid ||
        (recovery.bits.token.index - head) <= (localCandidate.bits.token.index - head))
    ledger.io.recover.valid          := externalWins || localCandidate.valid
    ledger.io.recover.bits.token     := Mux(externalWins, recovery.bits.token, localCandidate.bits.token)
    ledger.io.recover.bits.inclusive := Mux(externalWins, recovery.bits.inclusive, localInclusive)
    io.recoveryAccepted              := externalWins && ledger.io.recoveryAccepted
    io.redirect.valid                := !externalWins && localCandidate.valid && ledger.io.recoveryAccepted
    io.redirect.bits                 := localCandidate.bits
    when(automaticTrap && (io.recoveryAccepted || emptyTrap)) {
        io.redirect.valid       := true.B
        io.redirect.bits.token  := trapEvent.token
        io.redirect.bits.pc     := trapEvent.pc
        io.redirect.bits.target := trapTarget
    }
    io.invalidateFetch := systemInvalidate && io.redirect.valid &&
        io.redirect.bits.token.asUInt === systemComplete.bits.token.asUInt
    systemComplete.ready := !lsu.io.complete.valid && !mCompleteValid && ledger.io.completionAccepted(0)
    for (lane <- 0 until p.completionWidth) {
        val usedIssues = PopCount(selected.take(lane).map(_.valid)) +& reserveSystem +&
            reserveMemory +& reserveMulDiv +& directStoreReserve
        val candidates = (0 until p.robEntries).map { i =>
            val candidate = Wire(new Candidate)
            val used      = (0 until lane)
                .map(j => selected(j).valid && selected(j).bits === i.U)
                .foldLeft(false.B)(_ || _)
            candidate.valid := eligible(
                i
            ) && !used && usedIssues < p.issueWidth.U && !(if (lane == 0)
                                (lsu.io.complete.valid || mCompleteValid || systemComplete.valid || reserveSystem || reserveMemory || reserveMulDiv)
                            else false.B)
            candidate.index := i.U
            candidate.age   := ages(i)
            candidate
        }
        val choice = tournament(candidates)
        selected(lane).valid := choice.valid
        selected(lane).bits  := choice.index
        val entry        = queue(choice.index)
        val source1      = Mux(choice.valid, entry.renamed.source1, 0.U)
        val source2      = Mux(choice.valid, entry.renamed.source2, 0.U)
        val prepareStore = entry.request.memory && entry.request.store
        prepared(lane) := choice.valid && prepareStore && !killed(choice.index) && !ledger.io.headException.valid
        when(prepared(lane)) {
            storeAddressKnown(choice.index) := true.B
            storeAddress(choice.index)  := operandValue(source1) + entry.request.immediate
            when(operandReady(source2)) {
                storePrepared(choice.index) := true.B
                storeData(choice.index)     := operandValue(source2)
            }
        }
        val alu = Module(new IntegerAlu)
        alu.io.operation := entry.request.operation
        alu.io.word      := entry.request.word
        alu.io.left      := Mux(entry.request.usePc, entry.request.rename.pc, operandValue(source1))
        alu.io.right     := Mux(entry.request.useImmediate, entry.request.immediate, operandValue(source2))
        val branch = Module(new BranchUnit(p.compressedInstructions))
        val shortInstruction = p.compressedInstructions.B &&
            entry.request.rename.instruction(1, 0) =/= 3.U
        val nextSequential = entry.request.rename.pc + Mux(shortInstruction, 2.U, 4.U)
        branch.io.kind      := entry.request.controlFlow
        branch.io.pc        := entry.request.rename.pc
        branch.io.shortInstruction := shortInstruction
        branch.io.immediate := entry.request.immediate
        branch.io.left      := operandValue(source1)
        branch.io.right     := operandValue(source2)
        val isControl  = entry.request.controlFlow =/= ControlFlow.none
        val legal      = Mux(isControl, branch.io.legal, alu.io.legal)
        val misaligned = isControl && branch.io.misaligned
        completion(lane).token     := Mux(choice.valid, entry.renamed.token, 0.U.asTypeOf(new RobToken(p)))
        completion(lane).data      := Mux(isControl, branch.io.data, alu.io.result)
        completion(lane).nextPc    := Mux(isControl, branch.io.nextPc, nextSequential)
        completion(lane).exception := entry.request.fetchFault || entry.request.fetchPageFault || !legal || misaligned
        completion(lane).cause     := Mux(entry.request.fetchPageFault, MCause.InstrPageFault,
            Mux(entry.request.fetchFault, MCause.InstrAccessFault,
                Mux(!legal, MCause.IllegalInstr, MCause.InstrAddrMisaligned)))
        completion(lane).tval      := Mux(entry.request.fetchFault || entry.request.fetchPageFault,
            entry.request.fetchTval,
            Mux(!legal, entry.request.rename.instruction, branch.io.target))
        resolutions(lane).valid    := choice.valid && isControl && legal && !misaligned &&
            branch.io.nextPc =/= Mux(
                entry.request.predictedNextPc.valid,
                entry.request.predictedNextPc.bits,
                nextSequential
            )
        resolutions(lane).bits.token  := entry.renamed.token
        resolutions(lane).bits.pc     := entry.request.rename.pc
        resolutions(lane).bits.target := branch.io.nextPc
        // A live branch whose redirect cannot yet narrow an ongoing rollback retries after rollback.
        ledger.io.complete(lane).valid := choice.valid && !prepareStore && (!resolutions(lane).valid ||
            (io.redirect.valid && io.redirect.bits.token.asUInt === entry.renamed.token.asUInt))
        ledger.io.complete(lane).bits := completion(lane)
        if (lane == 0) {
            when(systemComplete.valid) {
                ledger.io.complete(lane).valid := !systemRedirect ||
                    (io.redirect.valid && io.redirect.bits.token.asUInt === systemComplete.bits.token.asUInt)
                ledger.io.complete(lane).bits := systemComplete.bits
            }
            when(multiplier.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                ledger.io.complete(lane).bits  := multiplier.io.complete.bits
            }
            when(mulDiv.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                ledger.io.complete(lane).bits  := mulDiv.io.complete.bits
            }
            when(lsu.io.complete.valid) {
                ledger.io.complete(lane).valid := true.B
                ledger.io.complete(lane).bits  := lsu.io.complete.bits
            }
        }
        io.issued(lane)       := ledger.io.complete(lane)
        io.issued(lane).valid := ledger.io.completionAccepted(lane)
        val completedIndex = ledger.io.complete(lane).bits.token.index
        val completedEntry = queue(completedIndex)
        when(ledger.io.completionAccepted(lane)) { pending(completedIndex) := false.B }
        when(
            ledger.io
                .completionAccepted(lane) && !ledger.io.complete(lane).bits.exception && completedEntry.renamed.writesRd
        ) {
            values(completedEntry.renamed.destination) := ledger.io.complete(lane).bits.data
            ready(completedEntry.renamed.destination)  := true.B
        }
    }
    when(fastLoadRetire && headRenamed.writesRd) {
        values(headRenamed.destination) := lsu.io.fastLoadPreview.bits.data
        ready(headRenamed.destination) := true.B
    }
    val aluIssues = (0 until p.completionWidth).map(lane =>
        ledger.io.completionAccepted(lane) && !(if (lane == 0)
                                                    (lsu.io.complete.valid || mCompleteValid || systemComplete.valid)
                                                else false.B)
    )
    io.mulDivOverlap := (mulDiv.io.busy || multiplier.io.busy) && aluIssues.reduce(_ || _)
    io.issueCount    := PopCount(aluIssues) + PopCount(
        prepared
    ) + systemStart + lsu.io.start.fire + mulDiv.io.start.fire + multiplier.io.start.fire + directStoreFire
    assert(PopCount(selected.map(_.valid)) +& reserveSystem +& reserveMemory +& reserveMulDiv +&
        directStoreReserve <= p.issueWidth.U)
    // Allocation takes priority over ready writes. Same-packet RAW reads the newly allocated, unready ID.
    for (lane <- 0 until p.renameWidth) {
        val renamed = ledger.io.renamed(lane)
        when(renamed.valid) {
            queue(renamed.bits.token.index).renamed := renamed.bits
            queue(renamed.bits.token.index).request := io.allocate(lane).bits
            pending(renamed.bits.token.index)       := true.B
            memoryLive(renamed.bits.token.index)    := io.allocate(lane).bits.memory
            storeAddressKnown(renamed.bits.token.index) := false.B
            storePrepared(renamed.bits.token.index) := false.B
            when(renamed.bits.writesRd && !renamed.bits.moveAlias) {
                ready(renamed.bits.destination) := false.B
            }
        }
    }
}
