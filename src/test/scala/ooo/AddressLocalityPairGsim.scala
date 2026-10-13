package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._

class AddressLocalityRowWrite extends Bundle {
    val valid = Bool()
    val index = UInt(4.W)
    val source1 = UInt(6.W)
    val source2 = UInt(6.W)
    val tag = UInt(64.W)
    val immediate = UInt(64.W)
    val store = Bool()
    val size = UInt(2.W)
    val saved = Bool()
    val savedAddress = UInt(64.W)
    val savedData = UInt(64.W)
}

class AddressLocalityWrite extends Bundle {
    val valid = Bool()
    val address = UInt(6.W)
    val data = UInt(64.W)
}

class AddressLocalityInput extends Bundle {
    val pending = UInt(16.W)
    val sourceReady = UInt(16.W)
    val prepared = UInt(16.W)
    // All unchanged fallback qualification terms except pending/store/non-head.
    val fallbackQualified = UInt(16.W)
    val directStoreReserve = Bool()
    // Already-qualified posted window, as determined before issued exclusion.
    val postedWindow = Bool()
    val commits = UInt(2.W)
    val recovery = Bool()
    val issued = Bool()
    val issuedIndex = UInt(4.W)
    val ready = Bool()
    // Test-only actual RTL mutant: bypass the empty owner's metadata mask.
    val rawIndex0 = Bool()
    val rawHeadMask = Bool()
    val excludeBeforeFallback = Bool()
    val row = new AddressLocalityRowWrite
    val write0 = new AddressLocalityWrite
    val write1 = new AddressLocalityWrite
}

class AddressLocalityRankObservation extends Bundle {
    val valid = Bool()
    val index = UInt(4.W)
    val owner = UInt(16.W)
    val source1 = UInt(6.W)
    val source2 = UInt(6.W)
    val left = UInt(64.W)
    val right = UInt(64.W)
    val immediate = UInt(64.W)
    val address = UInt(64.W)
    val data = UInt(64.W)
    val tag = UInt(64.W)
    val store = Bool()
    val size = UInt(2.W)
    val saved = Bool()
}

class AddressLocalitySideObservation extends Bundle {
    val head = UInt(4.W)
    val afterHead = UInt(16.W)
    val headOwner = UInt(16.W)
    val originalMask = UInt(16.W)
    val fallbackMask = UInt(16.W)
    val preparationMask = UInt(16.W)
    val rawHeadMaskApplied = Bool()
    val excludeBeforeFallbackApplied = Bool()
    val rank0 = new AddressLocalityRankObservation
    val rank1 = new AddressLocalityRankObservation
    val selectedValid = Bool()
    val selectedIndex = UInt(4.W)
    val useSecond = Bool()
    val requestFire = Bool()
    val requestIndex = UInt(4.W)
    val requestTag = UInt(64.W)
    val requestAddress = UInt(64.W)
    val requestData = UInt(64.W)
    val requestSize = UInt(2.W)
    val completeFire = Bool()
    val completeIndex = UInt(4.W)
    val completeTag = UInt(64.W)
    val completeAddress = UInt(64.W)
    val completeData = UInt(64.W)
    val completeSize = UInt(2.W)
    val requestCount = UInt(32.W)
    val completeCount = UInt(32.W)
    val rawIndex0Applied = Bool()
}

/** Component proof of the two address-locality changes. Both sides contain the
  * production head mask, oldest-two selector, one-hot metadata selection,
  * guarded immediate RAM and owner-banked PRF. Common fallback qualifications
  * arrive as boundary inputs; this is not a backend or recovery pipeline model.
  * A local head register advances on the same accepted-commit edge as the real
  * RegisteredRobHeadMask. Recovery changes eligibility, never the head itself.
  */
class AddressLocalitySlice(direct: Boolean) extends Module {
    val p = OooParams(robEntries = 16, physicalRegs = 48, registeredMemoryAddress = true,
        parallelMemoryPreparation = true, parallelMemoryPayload = true,
        compactMemoryOperandSelect = true, bankedIssuePayload = true,
        lvtPhysicalRegisterFile = true, parallelIssuePayload = true, parallelIssueRanks = true,
        earlyRankedOperands = true, precompleteMispredictedBranch = true,
        registeredBranchRedirect = true, registeredRobRetirement = true,
        registeredIssueHeadMask = true, directRank1MemorySourceIds = true,
        memoryPreparationHeadMask = direct, directRank0MemorySourceIds = direct)
    val io = IO(new Bundle {
        val in = Input(new AddressLocalityInput)
        val out = Output(new AddressLocalitySideObservation)
    })
    val queue = Reg(Vec(p.robEntries, new IntegerIssueEntry(p)))
    val saved = Reg(Vec(p.robEntries, Bool()))
    val savedAddress = Reg(Vec(p.robEntries, UInt(64.W)))
    val savedData = Reg(Vec(p.robEntries, UInt(64.W)))
    val row = io.in.row
    when(row.valid) {
        queue(row.index) := 0.U.asTypeOf(new IntegerIssueEntry(p))
        queue(row.index).renamed.source1 := row.source1
        queue(row.index).renamed.source2 := row.source2
        queue(row.index).renamed.token.index := row.index
        queue(row.index).renamed.token.tag := row.tag
        queue(row.index).request.memory := true.B
        queue(row.index).request.store := row.store
        queue(row.index).request.memorySize := row.size
        saved(row.index) := row.saved
        savedAddress(row.index) := row.savedAddress
        savedData(row.index) := row.savedData
    }
    val payload = Module(new BankedIssuePayload(p.robEntries, Seq.fill(2)(Set("immediate"))))
    payload.io.write := 0.U.asTypeOf(payload.io.write)
    payload.io.write(0).valid := row.valid
    payload.io.write(0).bits.index := row.index
    payload.io.write(0).bits.data.immediate := row.immediate
    val head = RegInit(0.U(p.robBits.W))
    head := head + io.in.commits
    val ageBoundary = Module(new RegisteredRobHeadMask(p))
    ageBoundary.io.head := head
    ageBoundary.io.commits := io.in.commits
    // Both variants use the same production registered age boundary for ranking.
    val localHeadOwner = MemoryPreparationLocality.headOwner(ageBoundary.io.afterHead)
    val referenceHeadOwner = UIntToOH(head, p.robEntries)
    val headOwner = if (p.memoryPreparationHeadMask)
        Mux(io.in.rawHeadMask, ageBoundary.io.afterHead, localHeadOwner) else referenceHeadOwner
    val originalMask = VecInit((0 until p.robEntries).map { i =>
        val isHead = if (p.memoryPreparationHeadMask) headOwner(i) else i.U === head
        io.in.pending(i) && (!queue(i).request.store || isHead) &&
            !(io.in.directStoreReserve && isHead) && (io.in.prepared(i) || io.in.sourceReady(i))
    }).asUInt
    val fallbackMask = VecInit((0 until p.robEntries).map { i =>
        val nonHead = if (p.memoryPreparationHeadMask) !headOwner(i) else i.U =/= head
        io.in.pending(i) && queue(i).request.store && nonHead && io.in.fallbackQualified(i)
    }).asUInt
    val issuedOwner = Mux(io.in.issued, UIntToOH(io.in.issuedIndex, p.robEntries), 0.U)
    val badOriginal = originalMask & ~issuedOwner
    val ordinaryPool = Mux(originalMask.orR, originalMask, fallbackMask)
    val correctPool = Mux(io.in.postedWindow && originalMask.orR, originalMask | fallbackMask, ordinaryPool)
    val badPool = Mux(badOriginal.orR, badOriginal, fallbackMask)
    val corruptPool = direct.B && io.in.excludeBeforeFallback
    val preparationMask = Mux(corruptPool, badPool, correctPool)
    val planner = Module(new MemoryPreparationSelector(p, parallelRanks = true, predecodedHead = true))
    planner.io.eligible := preparationMask
    planner.io.head := head
    planner.io.headMask.get := ageBoundary.io.afterHead
    planner.io.issued := io.in.issued
    planner.io.issuedIndex := io.in.issuedIndex
    io.out.head := head
    io.out.afterHead := ageBoundary.io.afterHead
    io.out.headOwner := headOwner
    io.out.originalMask := originalMask
    io.out.fallbackMask := fallbackMask
    io.out.preparationMask := preparationMask
    io.out.rawHeadMaskApplied := direct.B && io.in.rawHeadMask && headOwner =/= localHeadOwner
    io.out.excludeBeforeFallbackApplied := corruptPool && badPool =/= correctPool
    when(io.in.recovery) {
        assert(io.in.commits === 0.U, "fixture recovery holds current head")
    }
    val prf = Module(new OwnerBankedPhysicalRegisterFile(p.physicalRegs, readPorts = 4))
    for ((write, lane) <- Seq(io.in.write0, io.in.write1).zipWithIndex) {
        prf.io.write(lane).valid := write.valid
        prf.io.write(lane).bits.address := write.address
        prf.io.write(lane).bits.data := write.data
    }
    val observations = Seq(io.out.rank0, io.out.rank1)
    io.out.rawIndex0Applied := false.B
    for (rank <- 0 until 2) {
        val valid = if (rank == 0) planner.io.firstValid else planner.io.secondValid
        val index = if (rank == 0) planner.io.firstIndex else planner.io.secondIndex
        val owner = if (rank == 0) planner.io.firstOwner else planner.io.secondOwner
        def selected(words: Seq[UInt]): UInt = CircularIssueSelector.selectPayload(owner, words)
        val metadata = selected(queue.map(_.asUInt).toSeq).asTypeOf(new IntegerIssueEntry(p))
        payload.io.address(rank) := index
        payload.io.enable(rank) := owner.orR
        val entry = Wire(new IntegerIssueEntry(p))
        entry := metadata
        ImmutableIssuePayload.insert(entry.request, payload.io.data(rank))
        // Retain the previously qualified direct rank1 behavior on both sides.
        // Rank0 alone is the new OFF/ON source-ID distinction.
        val directIds = if (rank == 0) p.directRank0MemorySourceIds else p.directRank1MemorySourceIds
        val selectedSource1 = MemoryPreparationLocality.sourceId(entry.renamed.source1, valid, directIds)
        val selectedSource2 = MemoryPreparationLocality.sourceId(entry.renamed.source2, valid, directIds)
        val corrupt = (direct && rank == 0).B && io.in.rawIndex0 && !valid
        val source1 = Mux(corrupt, queue(0).renamed.source1, selectedSource1)
        val source2 = Mux(corrupt, queue(0).renamed.source2, selectedSource2)
        if (direct && rank == 0) {
            io.out.rawIndex0Applied := corrupt &&
                (source1 =/= selectedSource1 || source2 =/= selectedSource2)
        }
        prf.io.address(2 * rank) := source1
        prf.io.address(2 * rank + 1) := source2
        val out = observations(rank)
        out.valid := valid
        out.index := index
        out.owner := owner
        out.source1 := source1
        out.source2 := source2
        out.left := prf.io.data(2 * rank)
        out.right := prf.io.data(2 * rank + 1)
        out.immediate := entry.request.immediate
        out.saved := valid && entry.request.store && (owner & saved.asUInt).orR
        out.address := Mux(out.saved, selected(savedAddress.toSeq), out.left + out.immediate)
        out.data := Mux(out.saved, selected(savedData.toSeq), out.right)
        out.tag := entry.renamed.token.tag
        out.store := entry.request.store
        out.size := entry.request.memorySize
    }
    io.out.selectedValid := planner.io.selectedValid
    io.out.selectedIndex := planner.io.selectedIndex
    io.out.useSecond := planner.io.useSecond
    val choice = Mux(planner.io.useSecond, io.out.rank1, io.out.rank0)
    io.out.requestFire := planner.io.selectedValid && io.in.ready
    io.out.requestIndex := planner.io.selectedIndex
    io.out.requestTag := choice.tag
    io.out.requestAddress := choice.address
    io.out.requestData := choice.data
    io.out.requestSize := choice.size
    io.out.completeFire := RegNext(io.out.requestFire, false.B)
    // Capture every payload, including invalid cycles, as in the unconditional
    // payload profile. The valid bit alone authorizes sink side effects.
    io.out.completeIndex := RegNext(io.out.requestIndex)
    io.out.completeTag := RegNext(io.out.requestTag)
    io.out.completeAddress := RegNext(io.out.requestAddress)
    io.out.completeData := RegNext(io.out.requestData)
    io.out.completeSize := RegNext(io.out.requestSize)
    val requests = RegInit(0.U(32.W))
    val completes = RegInit(0.U(32.W))
    when(io.out.requestFire) { requests := requests + 1.U }
    when(io.out.completeFire) { completes := completes + 1.U }
    io.out.requestCount := requests
    io.out.completeCount := completes
}

class AddressLocalityPairGsim extends Module {
    val io = IO(new Bundle {
        val in = Input(new AddressLocalityInput)
        val reference = Output(new AddressLocalitySideObservation)
        val candidate = Output(new AddressLocalitySideObservation)
    })
    val reference = Module(new AddressLocalitySlice(direct = false))
    val candidate = Module(new AddressLocalitySlice(direct = true))
    reference.io.in := io.in
    candidate.io.in := io.in
    io.reference := reference.io.out
    io.candidate := candidate.io.out
}

object AddressLocalityPairGsimMain extends App {
    require(args.length == 1, "usage: AddressLocalityPairGsimMain <target-dir>")
    ChiselStage.emitCHIRRTLFile(new AddressLocalityPairGsim, Array("--target-dir", args.head))
}
