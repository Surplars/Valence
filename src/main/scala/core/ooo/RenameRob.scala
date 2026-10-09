package soc.core.ooo

import chisel3._
import chisel3.util._

/** Trusted system redirect from an irrevocable transaction authorized at the ROB head.
  * Unlike an inclusive architectural trap, this retains the current head (keep=1).
  * No caller-supplied token can become authoritative. headToken is an invariant
  * witness for the backend, not a production authorization comparison.
  */
class HeadSystemRecoveryPort(p: OooParams) extends Bundle {
    val valid = Input(Bool())
    val accepted = Output(Bool())
    val headToken = Output(new RobToken(p))
}

/** Rename/retirement ledger, not yet an executing CPU.
  *
  * A contiguous prefix is accepted only with dispatchReady. Commit is an ordered prefix. Recovery walks the ROB
  * backwards in groups, restoring mappings before recycling registers. Completion authorization is exposed so that future PRF
  * writes and wakeups use the same liveness decision as the ROB. Tags never silently wrap: exhaustion blocks allocation
  * until reset, which requires all external producers to have been reset/drained too.
  */
class RenameRob(val p: OooParams = OooParams()) extends Module {
    val io = IO(new Bundle {
        val allocate           = Input(Vec(p.renameWidth, Valid(new RenameRequest)))
        // Raw expanded rd is payload only; valid/writesRd retain all authorization.
        val rawDestinations = if (p.parallelArchitecturalDestinations)
            Some(Input(Vec(p.renameWidth, UInt(5.W)))) else None
        val rawRequests = if (p.tentativeRenameSources)
            Some(Input(Vec(p.renameWidth, new RenameRequest))) else None
        val fetchFaultMask = if (p.tentativeRenameSources) Some(Input(UInt(p.renameWidth.W))) else None
        val sourceCandidates = if (p.tentativeRenameSources)
            Some(Output(Vec(2, Vec(2, new RenameSourcePair(p))))) else None
        val dispatchReady      = Input(Bool())
        val renamed            = Output(Vec(p.renameWidth, Valid(new RenamedInstruction(p))))
        val complete           = Input(Vec(p.completionWidth, Valid(new BackendCompletion(p))))
        val sameCycleRetire    = Input(Vec(p.completionWidth, Bool()))
        // A producer may omit faults only for results forbidden from same-cycle
        // retirement. Full completion.exception still updates the ROB unchanged.
        val sameCycleFault = if (p.separateBranchRetireFault)
            Some(Input(Vec(p.completionWidth, Bool()))) else None
        val completionAccepted = Output(Vec(p.completionWidth, Bool()))
        val commitEnable       = Input(Bool())
        // A registered load-order check may release only the older prefix.
        // Invalid generations fail closed rather than weakening its boundary.
        val loadOrderRetireLimit = if (p.loadOrderOlderRetire)
            Some(Input(Valid(new RobToken(p)))) else None
        val fastHeadRetire     = Input(Valid(new BackendCompletion(p)))
        val commit             = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val pendingException   = Output(Valid(new HeadException(p)))
        val headException      = Output(Valid(new HeadException(p)))
        val recover            = Input(Valid(new RecoveryRequest(p)))
        // Side-effect-free admission check for arbitration with an execution-generated redirect.
        val recoveryProbe         = Input(Valid(new RecoveryRequest(p)))
        val recoveryProbeAccepted = Output(Bool())
        val parallelRecovery = if (p.parallelRecoveryAdmission) Some(new ParallelRecoveryPort(p)) else None
        val headTrap = if (p.fastHeadTrapRecovery) Some(new HeadTrapRecoveryPort) else None
        val headSystem = if (p.fastHeadSystemRecovery) Some(new HeadSystemRecoveryPort(p)) else None
        val recoveryAccepted      = Output(Bool())
        val recovering            = Output(Bool())
        val occupancy             = Output(UInt(p.countBits.W))
        val headValid             = Output(Bool())
        val headDone              = Output(Bool())
        val headPc                = Output(UInt(64.W))
        val freeCount             = Output(UInt(log2Ceil(p.physicalRegs + 1).W))
        val tagExhausted          = Output(Bool())
        // Stable read-only architectural mapping inspection, independent of generated hierarchy names.
        val inspectRegister    = Input(UInt(5.W))
        val speculativeMapping = Output(UInt(p.physBits.W))
        val committedMapping   = Output(UInt(p.physBits.W))
    })

    val entries    = Reg(Vec(p.robEntries, new RobEntry(p)))
    val head       = RegInit(0.U(p.robBits.W))
    val tail       = RegInit(0.U(p.robBits.W))
    val count      = RegInit(0.U(p.countBits.W))
    val rat        = RegInit(VecInit((0 until 32).map(_.U(p.physBits.W))))
    val committed  = RegInit(VecInit((0 until 32).map(_.U(p.physBits.W))))
    val free       = RegInit(VecInit((0 until p.physicalRegs).map(i => (i >= 32).B)))
    // An aliased move creates another mapping owner without allocating a PRF entry.
    // An old mapping is released only at commit; a new mapping is released on rollback.
    private val ownerBits = log2Ceil(p.robEntries + 33)
    val owners = if (p.moveAlias)
        Some(RegInit(VecInit((0 until p.physicalRegs).map(i => (if (i < 32) 1 else 0).U(ownerBits.W)))))
    else None
    val nextTag    = RegInit(0.U(p.tagBits.W))
    val exhausted  = RegInit(false.B)
    val recovering = RegInit(false.B)
    val keepCount  = RegInit(0.U(p.countBits.W))

    val allocationPayload = if (p.bankedRobPayload) Some(Module(new BankedRobPayload(p.robEntries))) else None
    allocationPayload.foreach { payload =>
        payload.io.head := head
        for (lane <- 0 until 2) {
            payload.io.write(lane).valid := io.renamed(lane).valid
            payload.io.write(lane).bits.index := io.renamed(lane).bits.token.index
            payload.io.write(lane).bits.data := Cat(io.allocate(lane).bits.pc, io.allocate(lane).bits.instruction)
        }
    }
    def retirementPayload(lane: Int): UInt = allocationPayload.map(_.io.read(lane)).getOrElse(
        Cat(entries(addIndex(head, lane.U)).pc.get, entries(addIndex(head, lane.U)).instruction.get))
    def headPc: UInt = retirementPayload(0)(95, 32)

    def addIndex(index: UInt, increment: UInt): UInt = (index + increment)(p.robBits - 1, 0)
    def age(index: UInt): UInt                       = (index - head)(p.robBits - 1, 0)
    def live(token: RobToken): Bool = age(token.index) < count && entries(token.index).tag === token.tag

    def canRecover(request: ValidIO[RecoveryRequest]): Bool = {
        val keep = age(request.bits.token.index).pad(p.countBits) + !request.bits.inclusive
        request.valid && live(request.bits.token) && (!recovering || keep < keepCount)
    }
    // An architectural automatic trap is always inclusive at THIS ledger's
    // head. Its keep count is zero independently of any local/externally
    // supplied token. Accept it directly, including a strict shrink of an
    // active nonzero rollback boundary; an already-zero boundary is not new.
    val acceptHeadTrap = io.headTrap.map(port =>
        port.valid && count =/= 0.U && (!recovering || keepCount =/= 0.U)).getOrElse(false.B)
    val headTrapBoundary = WireDefault(0.U.asTypeOf(Valid(new RecoveryRequest(p))))
    headTrapBoundary.valid := acceptHeadTrap
    headTrapBoundary.bits.token.index := head
    headTrapBoundary.bits.token.tag := entries(head).tag
    headTrapBoundary.bits.inclusive := true.B
    io.headTrap.foreach(_.accepted := acceptHeadTrap)
    // A valid external request at the same head has the original external tie
    // priority. Prequalify that arbitrary token independently of system.valid;
    // the trusted system path itself never indexes a tag using a supplied owner.
    val externalHeadKeep = Mux(io.recoveryProbe.bits.inclusive, 0.U(p.countBits.W), 1.U(p.countBits.W))
    val externalHeadWins = if (p.fastHeadSystemRecovery)
        io.recoveryProbe.valid && count =/= 0.U && io.recoveryProbe.bits.token.index === head &&
            io.recoveryProbe.bits.token.tag === entries(head).tag &&
            (!recovering || externalHeadKeep < keepCount)
    else false.B
    val headSystemRequest = io.headSystem.map(_.valid).getOrElse(false.B)
    val acceptHeadSystem = headSystemRequest && count =/= 0.U && !acceptHeadTrap && !externalHeadWins &&
        (!recovering || keepCount > 1.U)
    val headSystemBoundary = WireDefault(0.U.asTypeOf(Valid(new RecoveryRequest(p))))
    headSystemBoundary.valid := acceptHeadSystem
    headSystemBoundary.bits.token.index := head
    headSystemBoundary.bits.token.tag := entries(head).tag
    headSystemBoundary.bits.inclusive := false.B
    io.headSystem.foreach { port =>
        port.accepted := acceptHeadSystem
        port.headToken := headSystemBoundary.bits.token
        when(port.valid) {
            assert(count =/= 0.U, "a trusted system redirect must own a nonempty current head")
            assert(!recovering || keepCount =/= 0.U,
                "an irrevocable system owner cannot survive a zero-retained rollback")
            assert(!io.parallelRecovery.get.local.valid,
                "the backend routes a trusted head system redirect separately from ordinary local recovery")
        }
    }
    val headSystemKilled = VecInit((0 until p.robEntries).map(i => i.U =/= head)).asUInt
    val recoveryAdmission = if (p.parallelRecoveryAdmission) Some(Module(new ParallelRecoveryAdmission(p))) else None
    recoveryAdmission.foreach { check =>
        check.io.head := head
        check.io.count := count
        check.io.tags := VecInit(entries.map(_.tag))
        check.io.recovering := recovering
        check.io.keepCount := keepCount
        check.io.external := io.recoveryProbe
        check.io.local := io.parallelRecovery.get.local
        // Merge only at the consumers. In particular, a late automatic trap
        // never traverses ordinary age arbitration or the per-slot boundary
        // comparator before it cancels work. Ordinary token rules are intact.
        io.parallelRecovery.get.externalWins := acceptHeadTrap || (!acceptHeadSystem && check.io.externalWins)
        io.parallelRecovery.get.selected := Mux(acceptHeadTrap, headTrapBoundary,
            Mux(acceptHeadSystem, headSystemBoundary, check.io.selected))
        io.parallelRecovery.get.killed := Mux(acceptHeadTrap, Fill(p.robEntries, true.B),
            Mux(acceptHeadSystem, headSystemKilled, check.io.killed))
    }
    io.recoveryProbeAccepted := recoveryAdmission.map(_.io.externalAccepted).getOrElse(canRecover(io.recoveryProbe))
    val effectiveRecovery = recoveryAdmission.map(_.io.selected).getOrElse(io.recover)
    val boundaryAge    = age(effectiveRecovery.bits.token.index)
    val requestedKeep  = boundaryAge.pad(p.countBits) + !effectiveRecovery.bits.inclusive
    val ordinaryRecovery = recoveryAdmission.map(_.io.accepted).getOrElse(canRecover(io.recover))
    val acceptRecovery = acceptHeadTrap || acceptHeadSystem || ordinaryRecovery
    val ordinaryKeep = recoveryAdmission.map(_.io.activeKeep).getOrElse(Mux(ordinaryRecovery, requestedKeep, keepCount))
    val activeKeep = Mux(acceptHeadTrap, 0.U(p.countBits.W),
        Mux(acceptHeadSystem, 1.U(p.countBits.W), ordinaryKeep))
    val recoveryCycle  = recovering || acceptRecovery
    val remaining      = count - activeKeep
    val removedCount   = Mux(remaining > p.recoveryWidth.U, p.recoveryWidth.U, remaining)

    io.recoveryAccepted   := acceptRecovery
    io.recovering         := recovering
    io.occupancy          := count
    io.headValid          := count =/= 0.U
    io.headDone           := count =/= 0.U && entries(head).done
    io.headPc             := Mux(count =/= 0.U, headPc, 0.U)
    io.freeCount          := PopCount(free)
    io.tagExhausted       := exhausted
    io.speculativeMapping := rat(io.inspectRegister)
    io.committedMapping   := committed(io.inspectRegister)

    // Completions for instructions on a discarded path cannot write a newly reused PRF entry.
    for (lane <- 0 until p.completionWidth) {
        val completion = io.complete(lane)
        val duplicate  = (0 until lane)
            .map(i => io.complete(i).valid && io.complete(i).bits.token.asUInt === completion.bits.token.asUInt)
            .foldLeft(false.B)(_ || _)
        val ordinarySurvives = recoveryAdmission.map(_.io.survives(completion.bits.token.index))
            .getOrElse(!recoveryCycle || age(completion.bits.token.index) < activeKeep)
        val accepted = completion.valid && live(completion.bits.token) &&
            !entries(completion.bits.token.index).done && !duplicate && !acceptHeadTrap &&
            Mux(acceptHeadSystem, completion.bits.token.index === head, ordinarySurvives)
        io.completionAccepted(lane) := accepted
        io.sameCycleFault.foreach { faults =>
            when(accepted && io.sameCycleRetire(lane)) {
                assert(faults(lane) === completion.bits.exception,
                    "same-cycle retirement fault must equal full exception when retirement is allowed")
            }
        }
        when(accepted) {
            entries(completion.bits.token.index).done      := true.B
            entries(completion.bits.token.index).data      := completion.bits.data
            entries(completion.bits.token.index).nextPc    := completion.bits.nextPc
            entries(completion.bits.token.index).exception := completion.bits.exception
            entries(completion.bits.token.index).cause     := completion.bits.cause
            entries(completion.bits.token.index).tval      := completion.bits.tval
        }
    }

    val commitPrefix = Wire(Vec(p.commitWidth + 1, Bool()))
    val retireLimitAuthorized = io.loadOrderRetireLimit.map(limit =>
        !limit.valid || live(limit.bits)).getOrElse(true.B)
    commitPrefix(0) := io.commitEnable && !recoveryCycle && retireLimitAuthorized
    for (lane <- 0 until p.commitWidth) {
        val index = addIndex(head, lane.U)
        val entry = entries(index)
        // A non-faulting completion may retire at the head without a register handoff
        // through entries(index).done. The accepted token check also rejects stale or
        // recovery-path results before they can affect retirement.
        val finishing = (0 until p.completionWidth).map(i =>
            io.completionAccepted(i) && io.complete(i).bits.token.index === index &&
                !io.sameCycleFault.map(_(i)).getOrElse(io.complete(i).bits.exception))
        // A selected control-flow result can complete now while its commit waits
        // for the ROB entry registers; non-control results retain the fast path.
        val retiringNow = (0 until p.completionWidth).map(i =>
            finishing(i) && (if (p.registeredRobRetirement) io.sameCycleRetire(i) else true.B))
        val finishNow = retiringNow.reduce(_ || _)
        val fastHeadNow = if (lane == 0) io.fastHeadRetire.valid && !entry.done &&
            io.fastHeadRetire.bits.token.index === index && io.fastHeadRetire.bits.token.tag === entry.tag
        else false.B
        val olderThanLoadCheck = io.loadOrderRetireLimit.map(limit =>
            !limit.valid || lane.U < age(limit.bits.index)).getOrElse(true.B)
        val valid = commitPrefix(lane) && lane.U < count && olderThanLoadCheck &&
            ((entry.done && !entry.exception) || (!entry.done && (finishNow || fastHeadNow)))
        // Re-evaluate interrupt enables after a system instruction retires, before any younger retirement.
        commitPrefix(lane + 1) := valid && !(if (p.machineSystem) retirementPayload(lane)(6, 0) === "h73".U else false.B)
        io.commit(lane).valid  := valid
        io.commit(lane).bits.token.index := index
        io.commit(lane).bits.token.tag   := entry.tag
        io.commit(lane).bits.pc          := retirementPayload(lane)(95, 32)
        io.commit(lane).bits.instruction := retirementPayload(lane)(31, 0)
        io.commit(lane).bits.rd          := entry.rd
        io.commit(lane).bits.destination := entry.destination
        io.commit(lane).bits.writesRd    := entry.writesRd
        io.commit(lane).bits.data        := Mux(entry.done, entry.data,
            Mux(fastHeadNow, io.fastHeadRetire.bits.data,
                Mux1H(retiringNow.zip(io.complete.map(_.bits.data)))))
        io.commit(lane).bits.nextPc      := Mux(entry.done, entry.nextPc,
            Mux(fastHeadNow, io.fastHeadRetire.bits.nextPc,
                Mux1H(retiringNow.zip(io.complete.map(_.bits.nextPc)))))
        when(valid && entry.writesRd) {
            committed(entry.rd)        := entry.destination
            if (!p.moveAlias) free(entry.oldDestination) := true.B
        }
    }
    val committedCount = PopCount(io.commit.map(_.valid))
    when(io.fastHeadRetire.valid) {
        assert(io.commit(0).valid,
            "same-cycle memory completion must retire the current head")
    }

    io.pendingException               := io.headException
    io.pendingException.valid         := count =/= 0.U && entries(head).done && entries(head).exception && !recovering
    io.headException.valid            := io.pendingException.valid && !acceptRecovery
    io.headException.bits.token.index := head
    io.headException.bits.token.tag   := entries(head).tag
    io.headException.bits.pc          := headPc
    io.headException.bits.cause       := entries(head).cause
    io.headException.bits.tval        := entries(head).tval

    // Combinational mapping/free-list stages provide same-packet RAW and WAW forwarding.
    // Explicit element connections avoid GSIM splitArray's bulk-connect/dynamic-write limitation.
    val maps             = Seq.fill(p.renameWidth + 1)(Wire(Vec(32, UInt(p.physBits.W))))
    val available        = Seq.fill(p.renameWidth + 1)(Wire(Vec(p.physicalRegs, Bool())))
    // Budget fault alternatives from unmasked decode before late PMP permission.
    // Only scalar candidates/credits are selected by faults; actual prefix and
    // all RAT/free/owner writes below retain their original authorization.
    val faultCandidates = if (p.tentativeRenameSources)
        Some(Module(new FaultAwareRenameCandidates(p))) else None
    faultCandidates.foreach { candidate =>
        candidate.io.raw := io.rawRequests.get
        candidate.io.faults := io.fetchFaultMask.get
        candidate.io.free := free.asUInt
        for (r <- 0 until 32) { candidate.io.rat(r) := rat(r) }
        io.sourceCandidates.get := candidate.io.sources
    }
    val allocationPrefix = Wire(Vec(p.renameWidth + 1, Bool()))
    val freshRegisters = Wire(Vec(p.renameWidth, Bool()))
    val destinationCandidates = if (p.earlyRenameDestinations)
        Some(Module(new RenameDestinationCandidates(p.renameWidth, p.physicalRegs, p.parallelRenameRanks))) else None
    destinationCandidates.foreach { selector =>
        selector.io.free := free.asUInt
        selector.io.fresh := freshRegisters.asUInt
    }
    val admission = if (p.parallelRenameAdmission)
        Some(Module(new RenameAllocationCapacity(p.renameWidth, p.physicalRegs))) else None
    admission.foreach { capacity =>
        capacity.io.free := free.asUInt
        capacity.io.fresh := freshRegisters.asUInt
    }
    for (r <- 0 until 32) { maps(0)(r) := rat(r) }
    for (r <- 0 until p.physicalRegs) { available(0)(r) := free(r) }
    allocationPrefix(0) := io.dispatchReady && !recoveryCycle && !exhausted
    for (lane <- 0 until p.renameWidth) {
        val request     = io.allocate(lane)
        val architecturalRd = io.rawDestinations.map(_(lane)).getOrElse(request.bits.rd)
        val writesRd    = request.bits.writesRd && architecturalRd =/= 0.U
        io.rawDestinations.foreach { indices =>
            when(request.valid && request.bits.writesRd) {
                assert(indices(lane) === request.bits.rd, "raw destination must match every authorized writer")
            }
        }
        val instruction = request.bits.instruction
        val compressedMove = p.compressedInstructions.B && instruction(31, 16) === 0.U &&
            instruction(15, 13) === 4.U && !instruction(12) && instruction(1, 0) === 2.U &&
            instruction(11, 7) === request.bits.rd && instruction(6, 2) === request.bits.rs2 &&
            request.bits.rs1 === 0.U && request.bits.rs2 =/= 0.U
        val addiMove = instruction(6, 0) === "h13".U && instruction(14, 12) === 0.U &&
            instruction(31, 20) === 0.U && instruction(19, 15) === request.bits.rs1 &&
            instruction(11, 7) === request.bits.rd && request.bits.rs1 =/= 0.U
        val addMove = instruction(6, 0) === "h33".U && instruction(31, 25) === 0.U &&
            instruction(14, 12) === 0.U && instruction(11, 7) === request.bits.rd &&
            instruction(19, 15) === request.bits.rs1 && instruction(24, 20) === request.bits.rs2 &&
            ((request.bits.rs1 === 0.U && request.bits.rs2 =/= 0.U) ||
                (request.bits.rs2 === 0.U && request.bits.rs1 =/= 0.U))
        val alias = p.moveAlias.B && writesRd && (compressedMove || addiMove || addMove)
        freshRegisters(lane) := writesRd && !alias
        val aliasSource = Mux(compressedMove || (addMove && request.bits.rs1 === 0.U),
            maps(lane)(request.bits.rs2), maps(lane)(request.bits.rs1))
        val hasRegister = available(lane).asUInt.orR
        val ordinaryDestination = Mux(!writesRd, 0.U, Mux(alias, aliasSource,
            destinationCandidates.map(_.io.destination(lane))
                .getOrElse(PriorityEncoder(available(lane).asUInt))))
        val destination = faultCandidates.map(_.io.selected(lane).destination).getOrElse(ordinaryDestination)
        val source1 = faultCandidates.map(_.io.selected(lane).source1).getOrElse(maps(lane)(request.bits.rs1))
        val source2 = faultCandidates.map(_.io.selected(lane).source2).getOrElse(maps(lane)(request.bits.rs2))
        val oldDestination = faultCandidates.map(_.io.selected(lane).oldDestination)
            .getOrElse(Mux(writesRd, maps(lane)(architecturalRd), 0.U))
        val tag         = nextTag +& lane.U
        // Accepted prefixes need exactly the fresh-register prefix count. Do not
        // wait for lane 0's accepted/destination before deciding lane 1's credit.
        val registerCapacity = faultCandidates.map(_.io.capacity(lane))
            .getOrElse(admission.map(_.io.enough(lane)).getOrElse(!writesRd || alias || hasRegister))
        val accepted    = allocationPrefix(lane) && request.valid && count +& lane.U < p.robEntries.U &&
            registerCapacity && !tag(p.tagBits)
        allocationPrefix(lane + 1) := accepted
        for (r <- 0 until 32) {
            maps(lane + 1)(r) := Mux(accepted && writesRd && architecturalRd === r.U, destination, maps(lane)(r))
        }
        for (r <- 0 until p.physicalRegs) {
            available(lane + 1)(r) := available(lane)(r) && !(accepted && writesRd && destination === r.U)
        }
        if (p.tentativeRenameSources) {
            val raw = io.rawRequests.get(lane)
            val fault = io.fetchFaultMask.get(lane)
            when(request.valid) {
                assert(request.bits.pc === raw.pc && request.bits.instruction === raw.instruction,
                    "fault masking must retain original PC and raw instruction metadata")
                when(fault) {
                    assert(!request.bits.writesRd && request.bits.rd === 0.U &&
                        request.bits.rs1 === 0.U && request.bits.rs2 === 0.U,
                        "a fetch fault must remain a nonwriting x0-source rename request")
                }.otherwise {
                    assert(request.bits.asUInt === raw.asUInt,
                        "normal raw decoded rename must equal the original final request")
                }
            }
            when(allocationPrefix(lane) && request.valid) {
                assert(registerCapacity === (!writesRd || alias || hasRegister),
                    "fault-aware credits must match the authoritative accepted-prefix free budget")
            }
            when(accepted) {
                for (previous <- 0 until lane) {
                    when(io.allocate(previous).valid) {
                        assert(io.renamed(previous).valid,
                            "every valid preceding lane must be accepted before consuming a later candidate")
                    }
                    assert(io.allocate(previous).valid,
                        "an invalid allocation hole must block all later lanes")
                }
                assert(source1 === maps(lane)(request.bits.rs1) && source2 === maps(lane)(request.bits.rs2) &&
                    oldDestination === Mux(writesRd, maps(lane)(architecturalRd), 0.U),
                    "accepted scalar candidates preserve precise RAW/WAW and fault masking")
                assert(faultCandidates.get.io.selected(lane).writesRd === writesRd &&
                    faultCandidates.get.io.selected(lane).moveAlias === alias,
                    "fault-aware candidate writer/alias flags must equal final authorization")
                val expectedAlias = Mux(compressedMove || (addMove && request.bits.rs1 === 0.U),
                    maps(lane)(request.bits.rs2), maps(lane)(request.bits.rs1))
                val expectedDestination = Mux(!writesRd, 0.U, Mux(alias, expectedAlias,
                    PriorityEncoder(available(lane).asUInt)))
                assert(destination === expectedDestination,
                    "accepted candidate preserves x0, move aliases and ordered fresh-register selection")
            }
        }
        when(accepted && writesRd) {
            rat(architecturalRd) := destination
            if (!p.moveAlias) free(destination) := false.B
        }

        val index = addIndex(tail, lane.U)
        io.renamed(lane).valid               := accepted
        io.renamed(lane).bits.token.index    := index
        io.renamed(lane).bits.token.tag      := tag
        io.renamed(lane).bits.source1        := source1
        io.renamed(lane).bits.source2        := source2
        io.renamed(lane).bits.destination    := destination
        io.renamed(lane).bits.oldDestination := oldDestination
        io.renamed(lane).bits.writesRd       := writesRd
        io.renamed(lane).bits.moveAlias      := alias

        when(accepted) {
            entries(index)                := 0.U.asTypeOf(new RobEntry(p))
            entries(index).tag            := tag
            entries(index).pc.foreach(_ := request.bits.pc)
            entries(index).instruction.foreach(_ := request.bits.instruction)
            entries(index).rd             := request.bits.rd
            entries(index).writesRd       := writesRd
            entries(index).destination    := destination
            entries(index).oldDestination := oldDestination
        }
    }
    val allocatedCount = PopCount(io.renamed.map(_.valid))
    val advancedTag    = nextTag +& allocatedCount

    when(acceptHeadTrap) {
        assert(activeKeep === 0.U && count =/= 0.U,
            "head trap is an inclusive recovery of the nonempty current ledger")
        assert(!io.completionAccepted.reduce(_ || _) && !io.commit.map(_.valid).reduce(_ || _) &&
            !io.renamed.map(_.valid).reduce(_ || _),
            "head trap cancels all same-cycle completion, retirement and allocation")
    }

    when(acceptHeadSystem) {
        assert(activeKeep === 1.U && count =/= 0.U && !acceptHeadTrap && !externalHeadWins,
            "trusted system recovery retains exactly the current head with original external tie priority")
        assert(!io.commit.map(_.valid).reduce(_ || _) && !io.renamed.map(_.valid).reduce(_ || _),
            "system recovery blocks retirement and allocation while permitting only full-token head completion")
        for (lane <- 0 until p.completionWidth) {
            when(io.completionAccepted(lane)) {
                assert(io.complete(lane).bits.token.index === head &&
                    io.complete(lane).bits.token.tag === entries(head).tag,
                    "exclusive system recovery must not accept a younger or stale completion")
            }
        }
    }

    when(recoveryCycle) {
        keepCount  := activeKeep
        recovering := remaining > p.recoveryWidth.U
        tail := (tail - removedCount)(p.robBits - 1, 0)
        count := count - removedCount
        for (lane <- 0 until p.recoveryWidth) {
            val index = (tail - (lane + 1).U)(p.robBits - 1, 0)
            val removed = entries(index)
            when(lane.U < removedCount && removed.writesRd) {
                rat(removed.rd) := removed.oldDestination
                if (!p.moveAlias) free(removed.destination) := true.B
            }
        }
    }.otherwise {
        head  := addIndex(head, committedCount)
        tail  := addIndex(tail, allocatedCount)
        count := count + allocatedCount - committedCount
        when(allocatedCount =/= 0.U) {
            nextTag   := advancedTag
            exhausted := advancedTag(p.tagBits)
        }
    }
    owners.foreach { references =>
        // Count owners, not consumers: each rename creates one destination mapping;
        // commit drops the overwritten map, rollback drops the discarded new map.
        for (r <- 0 until p.physicalRegs) {
            val acquired = PopCount(io.renamed.map(a =>
                a.valid && a.bits.writesRd && a.bits.destination === r.U))
            val committedOld = PopCount(io.commit.map(c =>
                c.valid && entries(c.bits.token.index).writesRd &&
                    entries(c.bits.token.index).oldDestination === r.U))
            val rolledBack = PopCount((0 until p.recoveryWidth).map { lane =>
                val index = (tail - (lane + 1).U)(p.robBits - 1, 0)
                recoveryCycle && lane.U < removedCount && entries(index).writesRd &&
                    entries(index).destination === r.U
            })
            val released = committedOld +& rolledBack
            val next = references(r) +& acquired - released
            assert(references(r) +& acquired >= released, "move alias owner underflow")
            assert(next <= (p.robEntries + 32).U, "move alias owner overflow")
            references(r) := next(ownerBits - 1, 0)
            free(r) := next === 0.U
        }
    }
}
