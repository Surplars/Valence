package soc.core.ooo

import chisel3._
import chisel3.util._

class RenameSourcePair(p: OooParams) extends Bundle {
    val source1 = UInt(p.physBits.W)
    val source2 = UInt(p.physBits.W)
}

class RenamePayloadCandidate(p: OooParams) extends Bundle {
    val source1 = UInt(p.physBits.W)
    val source2 = UInt(p.physBits.W)
    val destination = UInt(p.physBits.W)
    val oldDestination = UInt(p.physBits.W)
    val writesRd = Bool()
    val moveAlias = Bool()
}

/** Two-lane combinational rename candidates, with zero state or grant inputs.
  * Raw decode is independent of fetch faults. Faults only select indexed scalar
  * candidates and four precomputed credits. No tentative RAT/free write occurs.
  */
class FaultAwareRenameCandidates(p: OooParams) extends Module {
    require(p.renameWidth == 2)
    val io = IO(new Bundle {
        val raw = Input(Vec(2, new RenameRequest))
        val faults = Input(UInt(2.W))
        val rat = Input(Vec(32, UInt(p.physBits.W)))
        val free = Input(UInt(p.physicalRegs.W))
        val selected = Output(Vec(2, new RenamePayloadCandidate(p)))
        val capacity = Output(UInt(2.W))
        // Lane 0: normal/zero. Lane 1: older-normal/older-fault.
        // These IDs never depend on fault, valid or accepted.
        val sources = Output(Vec(2, Vec(2, new RenameSourcePair(p))))
    })
    val firstOH = PriorityEncoderOH(io.free)
    val secondOH = PriorityEncoderOH(io.free & ~firstOH)
    val firstId = OHToUInt(firstOH)
    val secondId = OHToUInt(secondOH)
    val hasOne = io.free.orR
    val hasTwo = (io.free & ~firstOH).orR
    val rawWrites = io.raw.map(r => r.writesRd && r.rd =/= 0.U)
    def moveKinds(r: RenameRequest): (Bool, Bool, Bool) = {
        val instruction = r.instruction
        val compressed = p.compressedInstructions.B && instruction(31, 16) === 0.U &&
            instruction(15, 13) === 4.U && !instruction(12) && instruction(1, 0) === 2.U &&
            instruction(11, 7) === r.rd && instruction(6, 2) === r.rs2 && r.rs1 === 0.U && r.rs2 =/= 0.U
        val addi = instruction(6, 0) === "h13".U && instruction(14, 12) === 0.U &&
            instruction(31, 20) === 0.U && instruction(19, 15) === r.rs1 &&
            instruction(11, 7) === r.rd && r.rs1 =/= 0.U
        val add = instruction(6, 0) === "h33".U && instruction(31, 25) === 0.U &&
            instruction(14, 12) === 0.U && instruction(11, 7) === r.rd &&
            instruction(19, 15) === r.rs1 && instruction(24, 20) === r.rs2 &&
            ((r.rs1 === 0.U && r.rs2 =/= 0.U) || (r.rs2 === 0.U && r.rs1 =/= 0.U))
        (compressed, addi, add)
    }
    val kinds = io.raw.map(moveKinds)
    val rawAlias = kinds.zipWithIndex.map { case ((compressed, addi, add), lane) =>
        p.moveAlias.B && rawWrites(lane) && (compressed || addi || add)
    }
    val fresh = rawWrites.zip(rawAlias).map { case (writes, alias) => writes && !alias }
    def aliasValue(lane: Int, source1: UInt, source2: UInt): UInt =
        Mux(kinds(lane)._1 || (kinds(lane)._3 && io.raw(lane).rs1 === 0.U), source2, source1)
    val normal0 = Wire(new RenamePayloadCandidate(p))
    normal0.source1 := io.rat(io.raw(0).rs1)
    normal0.source2 := io.rat(io.raw(0).rs2)
    normal0.destination := Mux(!rawWrites(0), 0.U,
        Mux(rawAlias(0), aliasValue(0, normal0.source1, normal0.source2), firstId))
    normal0.oldDestination := Mux(rawWrites(0), io.rat(io.raw(0).rd), 0.U)
    normal0.writesRd := rawWrites(0)
    normal0.moveAlias := rawAlias(0)
    // Only indexed scalar reads are budgeted, not additional RAT copies.
    def afterOlder(architectural: UInt): UInt =
        Mux(rawWrites(0) && io.raw(0).rd === architectural, normal0.destination, io.rat(architectural))
    val normal1 = Wire(new RenamePayloadCandidate(p))
    normal1.source1 := afterOlder(io.raw(1).rs1)
    normal1.source2 := afterOlder(io.raw(1).rs2)
    normal1.destination := Mux(!rawWrites(1), 0.U,
        Mux(rawAlias(1), aliasValue(1, normal1.source1, normal1.source2), Mux(fresh(0), secondId, firstId)))
    normal1.oldDestination := Mux(rawWrites(1), afterOlder(io.raw(1).rd), 0.U)
    normal1.writesRd := rawWrites(1)
    normal1.moveAlias := rawAlias(1)
    val olderFault1 = Wire(new RenamePayloadCandidate(p))
    olderFault1.source1 := io.rat(io.raw(1).rs1)
    olderFault1.source2 := io.rat(io.raw(1).rs2)
    olderFault1.destination := Mux(!rawWrites(1), 0.U,
        Mux(rawAlias(1), aliasValue(1, olderFault1.source1, olderFault1.source2), firstId))
    olderFault1.oldDestination := Mux(rawWrites(1), io.rat(io.raw(1).rd), 0.U)
    olderFault1.writesRd := rawWrites(1)
    olderFault1.moveAlias := rawAlias(1)
    val zero = 0.U.asTypeOf(new RenamePayloadCandidate(p))
    io.selected(0) := Mux(io.faults(0), zero, normal0)
    io.selected(1) := Mux(io.faults(1), zero, Mux(io.faults(0), olderFault1, normal1))
    def enough(a: Bool, b: Bool): Bool = Mux(a && b, hasTwo, Mux(a || b, hasOne, true.B))
    val capacity0 = enough(fresh(0), false.B)
    val capacity1 = MuxLookup(io.faults, false.B)(Seq(
        0.U -> enough(fresh(0), fresh(1)), 1.U -> enough(false.B, fresh(1)),
        2.U -> capacity0, 3.U -> true.B))
    io.capacity := Cat(capacity1, Mux(io.faults(0), true.B, capacity0))
    io.sources(0)(0).source1 := normal0.source1
    io.sources(0)(0).source2 := normal0.source2
    io.sources(0)(1) := 0.U.asTypeOf(new RenameSourcePair(p))
    io.sources(1)(0).source1 := normal1.source1
    io.sources(1)(0).source2 := normal1.source2
    io.sources(1)(1).source1 := olderFault1.source1
    io.sources(1)(1).source2 := olderFault1.source2
}

/** Read candidate IDs before faults select ready Booleans. Accepted wake/reserve
  * events are unchanged, and reserve retains priority over wake.
  */
class FaultAwareAllocationReady(p: OooParams) extends Module {
    require(p.renameWidth == 2)
    val io = IO(new Bundle {
        val sources = Input(Vec(2, Vec(2, new RenameSourcePair(p))))
        val faults = Input(UInt(2.W))
        val physical = Input(UInt(p.physicalRegs.W))
        val wake = Input(Vec(p.completionWidth + 1, Valid(UInt(p.physBits.W))))
        val reserve = Input(Vec(2, Valid(UInt(p.physBits.W))))
        val allocationExecutionClass = if (p.registeredLoadResultReady) Some(Input(Vec(2, Bool()))) else None
        val heldLoads = if (p.registeredLoadResultReady)
            Some(Input(Vec(p.memoryEntries, Valid(UInt(p.physBits.W))))) else None
        val publishedLoads = if (p.registeredLoadResultReady)
            Some(Input(Vec(p.memoryEntries, Valid(UInt(p.physBits.W))))) else None
        val ready1 = Output(Vec(2, Bool()))
        val ready2 = Output(Vec(2, Bool()))
    })
    def reserving(index: UInt): Bool =
        io.reserve.map(r => r.valid && r.bits === index).reduce(_ || _)
    def baseNext(index: UInt, execution: Bool = false.B): Bool = {
        val current = (0 until p.physicalRegs).map(r => index === r.U && io.physical(r)).reduce(_ || _)
        val waking = io.wake.map(w => w.valid && w.bits === index).reduce(_ || _)
        if (p.registeredLoadResultReady) {
            val stable = io.heldLoads.get.map(h => h.valid && h.bits === index).reduce(_ || _)
            (current || waking || (execution && stable)) && !reserving(index)
        } else (current || waking) && !reserving(index)
    }
    val zeroReady = baseNext(0.U(p.physBits.W))
    def selected(lane: Int, candidates: Seq[Bool], zero: Bool): Bool = {
        if (lane == 0) Mux(io.faults(0), zero, candidates(0))
        else Mux(io.faults(1), zero, Mux(io.faults(0), candidates(1), candidates(0)))
    }
    def allocated(lane: Int, indices: Seq[UInt]): Bool = {
        val execution = io.allocationExecutionClass.map(_(lane)).getOrElse(false.B)
        val base = selected(lane, indices.map(index => baseNext(index, execution)), zeroReady)
        if (p.registeredLoadResultReady) {
            // Match candidate IDs and apply class, reserve priority and fault choice
            // before late publication validity. Keep the same-edge incoming-row wake;
            // faulted lanes use zeroReady and cannot gain an execution-only publication.
            val publishing = io.publishedLoads.get.map { load =>
                val candidates = indices.map(index =>
                    execution && !reserving(index) && load.bits === index)
                load.valid && selected(lane, candidates, false.B)
            }.reduce(_ || _)
            base || publishing
        } else base
    }
    for (lane <- 0 until p.renameWidth) {
        io.ready1(lane) := allocated(lane, io.sources(lane).map(_.source1).toSeq)
        io.ready2(lane) := allocated(lane, io.sources(lane).map(_.source2).toSeq)
    }
}
