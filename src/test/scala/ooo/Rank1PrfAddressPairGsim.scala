package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._

class Rank1PrfRowWrite extends Bundle {
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

class Rank1PrfWrite extends Bundle {
    val valid = Bool()
    val address = UInt(6.W)
    val data = UInt(64.W)
}

class Rank1PrfInput extends Bundle {
    val eligible = UInt(16.W)
    val head = UInt(4.W)
    val issued = Bool()
    val issuedIndex = UInt(4.W)
    val ready = Bool()
    // Test-only actual RTL mutant: bypass the empty owner's metadata mask.
    val rawIndex0 = Bool()
    val row = new Rank1PrfRowWrite
    val write0 = new Rank1PrfWrite
    val write1 = new Rank1PrfWrite
}

class Rank1PrfRankObservation extends Bundle {
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

class Rank1PrfSideObservation extends Bundle {
    val rank0 = new Rank1PrfRankObservation
    val rank1 = new Rank1PrfRankObservation
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

/** A component proof, not an IntegerBackend/LSU substitute. Both sides use the
  * real oldest-two selector, whole-entry one-hot metadata helper, guarded
  * immediate RAM and asynchronous owner-banked PRF. The only OFF/ON difference
  * is the rank1 source-ID clear. The small sink below merely makes invalid
  * preparation side effects observable; it is not a CPU completion pipeline.
  */
class Rank1PrfAddressSlice(direct: Boolean) extends Module {
    val p = OooParams(robEntries = 16, physicalRegs = 48, registeredMemoryAddress = true,
        parallelMemoryPreparation = true, parallelMemoryPayload = true,
        compactMemoryOperandSelect = true, bankedIssuePayload = true,
        lvtPhysicalRegisterFile = true, directRank1MemorySourceIds = direct)
    val io = IO(new Bundle {
        val in = Input(new Rank1PrfInput)
        val out = Output(new Rank1PrfSideObservation)
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
    val planner = Module(new MemoryPreparationSelector(p, parallelRanks = true))
    planner.io.eligible := io.in.eligible
    planner.io.head := io.in.head
    planner.io.issued := io.in.issued
    planner.io.issuedIndex := io.in.issuedIndex
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
        val selectedSource1 = if (p.directRank1MemorySourceIds && rank == 1) entry.renamed.source1
            else Mux(valid, entry.renamed.source1, 0.U)
        val selectedSource2 = if (p.directRank1MemorySourceIds && rank == 1) entry.renamed.source2
            else Mux(valid, entry.renamed.source2, 0.U)
        val corrupt = (direct && rank == 1).B && io.in.rawIndex0 && !valid
        val source1 = Mux(corrupt, queue(0).renamed.source1, selectedSource1)
        val source2 = Mux(corrupt, queue(0).renamed.source2, selectedSource2)
        if (direct && rank == 1) {
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

class Rank1PrfAddressPairGsim extends Module {
    val io = IO(new Bundle {
        val in = Input(new Rank1PrfInput)
        val reference = Output(new Rank1PrfSideObservation)
        val candidate = Output(new Rank1PrfSideObservation)
    })
    val reference = Module(new Rank1PrfAddressSlice(direct = false))
    val candidate = Module(new Rank1PrfAddressSlice(direct = true))
    reference.io.in := io.in
    candidate.io.in := io.in
    io.reference := reference.io.out
    io.candidate := candidate.io.out
}

object Rank1PrfAddressPairGsimMain extends App {
    require(args.length == 1, "usage: Rank1PrfAddressPairGsimMain <target-dir>")
    ChiselStage.emitCHIRRTLFile(new Rank1PrfAddressPairGsim, Array("--target-dir", args.head))
}
