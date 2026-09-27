package soc.core.ooo

import chisel3._
import chisel3.util._

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
        val dispatchReady      = Input(Bool())
        val renamed            = Output(Vec(p.renameWidth, Valid(new RenamedInstruction(p))))
        val complete           = Input(Vec(p.completionWidth, Valid(new BackendCompletion(p))))
        val completionAccepted = Output(Vec(p.completionWidth, Bool()))
        val commitEnable       = Input(Bool())
        val fastHeadRetire     = Input(Valid(new BackendCompletion(p)))
        val commit             = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val pendingException   = Output(Valid(new HeadException(p)))
        val headException      = Output(Valid(new HeadException(p)))
        val recover            = Input(Valid(new RecoveryRequest(p)))
        // Side-effect-free admission check for arbitration with an execution-generated redirect.
        val recoveryProbe         = Input(Valid(new RecoveryRequest(p)))
        val recoveryProbeAccepted = Output(Bool())
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

    def addIndex(index: UInt, increment: UInt): UInt = (index + increment)(p.robBits - 1, 0)
    def age(index: UInt): UInt                       = (index - head)(p.robBits - 1, 0)
    def live(token: RobToken): Bool = age(token.index) < count && entries(token.index).tag === token.tag

    def canRecover(request: ValidIO[RecoveryRequest]): Bool = {
        val keep = age(request.bits.token.index).pad(p.countBits) + !request.bits.inclusive
        request.valid && live(request.bits.token) && (!recovering || keep < keepCount)
    }
    io.recoveryProbeAccepted := canRecover(io.recoveryProbe)
    val boundaryAge    = age(io.recover.bits.token.index)
    val requestedKeep  = boundaryAge.pad(p.countBits) + !io.recover.bits.inclusive
    val acceptRecovery = canRecover(io.recover)
    val activeKeep     = Mux(acceptRecovery, requestedKeep, keepCount)
    val recoveryCycle  = recovering || acceptRecovery
    val remaining      = count - activeKeep
    val removedCount   = Mux(remaining > p.recoveryWidth.U, p.recoveryWidth.U, remaining)

    io.recoveryAccepted   := acceptRecovery
    io.recovering         := recovering
    io.occupancy          := count
    io.headValid          := count =/= 0.U
    io.headDone           := count =/= 0.U && entries(head).done
    io.headPc             := Mux(count =/= 0.U, entries(head).pc, 0.U)
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
        val accepted = completion.valid && live(completion.bits.token) &&
            !entries(completion.bits.token.index).done && !duplicate &&
            (!recoveryCycle || age(completion.bits.token.index) < activeKeep)
        io.completionAccepted(lane) := accepted
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
    commitPrefix(0) := io.commitEnable && !recoveryCycle
    for (lane <- 0 until p.commitWidth) {
        val index = addIndex(head, lane.U)
        val entry = entries(index)
        // A non-faulting completion may retire at the head without a register handoff
        // through entries(index).done. The accepted token check also rejects stale or
        // recovery-path results before they can affect retirement.
        val finishing = (0 until p.completionWidth).map(i =>
            io.completionAccepted(i) && io.complete(i).bits.token.index === index &&
                !io.complete(i).bits.exception)
        val finishNow = finishing.reduce(_ || _)
        val fastHeadNow = if (lane == 0) io.fastHeadRetire.valid && !entry.done &&
            io.fastHeadRetire.bits.token.index === index && io.fastHeadRetire.bits.token.tag === entry.tag
        else false.B
        val valid = commitPrefix(lane) && lane.U < count &&
            ((entry.done && !entry.exception) || (!entry.done && (finishNow || fastHeadNow)))
        // Re-evaluate interrupt enables after a system instruction retires, before any younger retirement.
        commitPrefix(lane + 1) := valid && !(if (p.machineSystem) entry.instruction(6, 0) === "h73".U else false.B)
        io.commit(lane).valid  := valid
        io.commit(lane).bits.token.index := index
        io.commit(lane).bits.token.tag   := entry.tag
        io.commit(lane).bits.pc          := entry.pc
        io.commit(lane).bits.instruction := entry.instruction
        io.commit(lane).bits.rd          := entry.rd
        io.commit(lane).bits.destination := entry.destination
        io.commit(lane).bits.writesRd    := entry.writesRd
        io.commit(lane).bits.data        := Mux(entry.done, entry.data,
            Mux(fastHeadNow, io.fastHeadRetire.bits.data,
                Mux1H(finishing.zip(io.complete.map(_.bits.data)))))
        io.commit(lane).bits.nextPc      := Mux(entry.done, entry.nextPc,
            Mux(fastHeadNow, io.fastHeadRetire.bits.nextPc,
                Mux1H(finishing.zip(io.complete.map(_.bits.nextPc)))))
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
    io.headException.bits.pc          := entries(head).pc
    io.headException.bits.cause       := entries(head).cause
    io.headException.bits.tval        := entries(head).tval

    // Combinational mapping/free-list stages provide same-packet RAW and WAW forwarding.
    // Explicit element connections avoid GSIM splitArray's bulk-connect/dynamic-write limitation.
    val maps             = Seq.fill(p.renameWidth + 1)(Wire(Vec(32, UInt(p.physBits.W))))
    val available        = Seq.fill(p.renameWidth + 1)(Wire(Vec(p.physicalRegs, Bool())))
    val allocationPrefix = Wire(Vec(p.renameWidth + 1, Bool()))
    for (r <- 0 until 32) { maps(0)(r) := rat(r) }
    for (r <- 0 until p.physicalRegs) { available(0)(r) := free(r) }
    allocationPrefix(0) := io.dispatchReady && !recoveryCycle && !exhausted
    for (lane <- 0 until p.renameWidth) {
        val request     = io.allocate(lane)
        val writesRd    = request.bits.writesRd && request.bits.rd =/= 0.U
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
        val aliasSource = Mux(compressedMove || (addMove && request.bits.rs1 === 0.U),
            maps(lane)(request.bits.rs2), maps(lane)(request.bits.rs1))
        val hasRegister = available(lane).asUInt.orR
        val destination = Mux(!writesRd, 0.U, Mux(alias, aliasSource,
            PriorityEncoder(available(lane).asUInt)))
        val tag         = nextTag +& lane.U
        val accepted    = allocationPrefix(lane) && request.valid && count +& lane.U < p.robEntries.U &&
            (!writesRd || alias || hasRegister) && !tag(p.tagBits)
        allocationPrefix(lane + 1) := accepted
        for (r <- 0 until 32) {
            maps(lane + 1)(r) := Mux(accepted && writesRd && request.bits.rd === r.U, destination, maps(lane)(r))
        }
        for (r <- 0 until p.physicalRegs) {
            available(lane + 1)(r) := available(lane)(r) && !(accepted && writesRd && destination === r.U)
        }
        when(accepted && writesRd) {
            rat(request.bits.rd) := destination
            if (!p.moveAlias) free(destination) := false.B
        }

        val index = addIndex(tail, lane.U)
        io.renamed(lane).valid               := accepted
        io.renamed(lane).bits.token.index    := index
        io.renamed(lane).bits.token.tag      := tag
        io.renamed(lane).bits.source1        := maps(lane)(request.bits.rs1)
        io.renamed(lane).bits.source2        := maps(lane)(request.bits.rs2)
        io.renamed(lane).bits.destination    := destination
        io.renamed(lane).bits.oldDestination := Mux(writesRd, maps(lane)(request.bits.rd), 0.U)
        io.renamed(lane).bits.writesRd       := writesRd
        io.renamed(lane).bits.moveAlias      := alias

        when(accepted) {
            entries(index)                := 0.U.asTypeOf(new RobEntry(p))
            entries(index).tag            := tag
            entries(index).pc             := request.bits.pc
            entries(index).instruction    := request.bits.instruction
            entries(index).rd             := request.bits.rd
            entries(index).writesRd       := writesRd
            entries(index).destination    := destination
            entries(index).oldDestination := Mux(writesRd, maps(lane)(request.bits.rd), 0.U)
        }
    }
    val allocatedCount = PopCount(io.renamed.map(_.valid))
    val advancedTag    = nextTag +& allocatedCount

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
