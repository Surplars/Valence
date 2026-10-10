package soc.core.ooo

import chisel3._
import chisel3.util._

/** Bounded RAM read concurrency over a strictly ordered-response data port. See docs/bare-core-ipc.md for throughput,
  * cancellation and platform contracts.
  */
class ParallelLoadStoreUnit(p: OooParams) extends Module {
    private val indexBits = math.max(1, log2Ceil(p.memoryEntries))
    val io                = IO(new Bundle {
        val start          = Flipped(Decoupled(new MemoryOperation(p)))
        // Sideband belongs to the accepted start owner, never a ROB lookup at completion.
        val issueDestination = if (p.registeredLoadIssueForwarding)
            Some(Input(Valid(UInt(p.physBits.W)))) else None
        val completedIssueDestination = if (p.registeredLoadIssueForwarding)
            Some(Output(Valid(UInt(p.physBits.W)))) else None
        val parallel       = Input(Bool())
        val issueAvailable = Output(Bool())
        val memory         = new DataPort
        val postedProof = p.postedProofConfig.map(c => Output(Valid(new PostedStoreProof(c))))
        val canonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap)
            Some(Output(Valid(new CanonicalStoreOrigin(p)))) else None
        val relaxStoreOwner = if (p.canonicalVirtualStoreOverlap)
            Some(Input(Valid(new RobToken(p)))) else None
        val complete       = Decoupled(new BackendCompletion(p))
        val cancel         = Input(Vec(p.memoryEntries, Bool()))
        val fastStoreRetire = Input(Bool())
        val fastLoadRetire = Input(Bool())
        val fastLoadPreview = Output(Valid(new BackendCompletion(p)))
        val owner          = Output(Vec(p.memoryEntries, new RobToken(p)))
        val requestOwner   = Output(Valid(new RobToken(p)))
        val live           = Output(Vec(p.memoryEntries, Bool()))
        val phase          = Output(Vec(p.memoryEntries, UInt(2.W)))
        val busy           = Output(Bool())
        val discarded      = Output(Bool())
        val forwarded      = Output(Bool())
        val forwardStore   = Output(Valid(new StoreForward(p)))
    })
    val slots      = Seq.fill(p.memoryEntries)(Module(new LoadStoreUnit(p)))
    val parallel   = RegInit(VecInit(Seq.fill(p.memoryEntries)(false.B)))
    val requestAccepted = if (p.canonicalVirtualStoreOverlap)
        Some(RegInit(VecInit(Seq.fill(p.memoryEntries)(false.B)))) else None
    val certifiedStoreClass = if (p.canonicalVirtualStoreOverlap)
        Some(RegInit(VecInit(Seq.fill(p.memoryEntries)(false.B)))) else None
    val completion = Module(new RRArbiter(new BackendCompletion(p), p.memoryEntries))
    for ((slot, i) <- slots.zipWithIndex) {
        completion.io.in(i) <> slot.io.complete
        slot.io.cancel := io.cancel(i)
        slot.io.fastStoreRetire := io.fastStoreRetire && slot.io.start.fire
        io.owner(i)    := slot.io.owner
        io.live(i)     := slot.io.busy
        io.phase(i)    := slot.io.phase
    }
    io.completedIssueDestination.foreach { destination =>
        val owners = Reg(Vec(p.memoryEntries, Valid(UInt(p.physBits.W))))
        for ((slot, i) <- slots.zipWithIndex) {
            when(slot.io.complete.valid) {
                assert(slot.io.complete.bits.token.asUInt === slot.io.owner.asUInt,
                    "load forwarding sideband and completion retain the same slot owner")
            }
            when(slot.io.start.fire) {
                owners(i).valid := io.issueDestination.get.valid && io.issueDestination.get.bits =/= 0.U &&
                    !io.start.bits.store && !io.start.bits.atomic
                owners(i).bits := io.issueDestination.get.bits
            }
        }
        // Both completion and sideband use the same existing arbiter selection.
        // Reads see the old registers when completion and replacement coincide.
        val selected = Mux1H((0 until p.memoryEntries).map(i =>
            (completion.io.chosen === i.U) -> owners(i)))
        destination.valid := completion.io.out.valid && !completion.io.out.bits.exception && selected.valid
        destination.bits := selected.bits
    }
    io.complete <> completion.io.out
    io.busy         := slots.map(_.io.busy).reduce(_ || _)
    io.discarded    := slots.map(_.io.discarded).reduce(_ || _)
    io.forwarded    := slots.map(_.io.forwarded).reduce(_ || _)
    io.forwardStore := Mux1H(
        (0 until p.memoryEntries).map(i =>
            (completion.io.out.valid && completion.io.chosen === i.U) -> slots(i).io.forwardStore
        )
    )

    // Prefer replacing the completing owner to preserve completion/start overlap and store forwarding.
    // Selection uses only registered slot state, not ready or same-cycle cancellation.
    val empty         = VecInit(slots.map(s => !s.io.busy))
    val chosen        = Mux(completion.io.out.valid, completion.io.chosen, PriorityEncoder(empty))
    val available     = completion.io.out.valid || empty.asUInt.orR
    val othersIdle    = (0 until p.memoryEntries).map(i => chosen === i.U || !slots(i).io.busy).reduce(_ && _)
    val ordinaryPrechecked = io.start.bits.precheckedLoad && io.start.bits.virtualized &&
        !io.start.bits.store && !io.start.bits.atomic && !io.start.bits.forward.valid
    val exemptSerial = (0 until p.memoryEntries).map { i =>
        io.relaxStoreOwner.map(owner => owner.valid && ordinaryPrechecked && io.parallel &&
            slots(i).io.busy && !parallel(i) && requestAccepted.get(i) && certifiedStoreClass.get(i) &&
            owner.bits.asUInt === slots(i).io.owner.asUInt).getOrElse(false.B)
    }
    val noOtherSerial = (0 until p.memoryEntries)
        .map(i => !slots(i).io.busy || parallel(i) || (completion.io.out.valid && chosen === i.U) || exemptSerial(i))
        .reduce(_ && _)
    io.issueAvailable := available && noOtherSerial && (io.parallel || othersIdle)
    io.start.ready    := io.issueAvailable && Mux1H(
        (0 until p.memoryEntries).map(i => (chosen === i.U) -> slots(i).io.start.ready)
    )
    for ((slot, i) <- slots.zipWithIndex) {
        slot.io.start.valid := io.start.valid && io.issueAvailable && chosen === i.U
        slot.io.start.bits  := io.start.bits
        when(slot.io.start.fire) { parallel(i) := io.parallel }
        requestAccepted.foreach { accepted =>
            when(slot.io.start.fire) { accepted(i) := false.B }
            // Fire belongs to the selected accepted operation, including start/request on the same edge.
            when(slot.io.memory.request.fire) { accepted(i) := true.B }
            when(slot.io.start.fire) {
                certifiedStoreClass.get(i) := slot.io.start.bits.canonicalStoreEpoch.get.valid &&
                    slot.io.start.bits.store && slot.io.start.bits.virtualized && !slot.io.start.bits.atomic
            }
            when(io.start.fire && exemptSerial(i)) {
                assert(ordinaryPrechecked && !io.cancel(i) && accepted(i) && certifiedStoreClass.get(i))
                assert(io.relaxStoreOwner.get.bits.asUInt === slot.io.owner.asUInt)
            }
        }
    }

    // Hold arbitration under request backpressure, even if a new slot becomes eligible meanwhile.
    val requests    = Module(new RRArbiter(new DataRequest, p.memoryEntries))
    val locked      = RegInit(false.B)
    val lockedIndex = Reg(UInt(indexBits.W))
    for ((slot, i) <- slots.zipWithIndex) {
        requests.io.in(i).valid      := slot.io.memory.request.valid && (!locked || lockedIndex === i.U)
        requests.io.in(i).bits       := slot.io.memory.request.bits
        slot.io.memory.request.ready := requests.io.in(i).ready && (!locked || lockedIndex === i.U)
    }
    io.requestOwner.valid := requests.io.out.valid
    io.requestOwner.bits := Mux1H((0 until p.memoryEntries).map(i =>
        (requests.io.chosen === i.U) -> Mux(slots(i).io.start.fire,
            slots(i).io.start.bits.token, slots(i).io.owner)))
    // A slot is never reused until its response and completion have both been consumed.
    val owners = Module(new Queue(UInt(indexBits.W), p.memoryEntries, pipe = false, flow = true))
    io.fastLoadPreview.valid := owners.io.deq.valid && Mux1H(
        (0 until p.memoryEntries).map(i =>
            (owners.io.deq.bits === i.U) -> slots(i).io.fastLoadPreview.valid))
    io.fastLoadPreview.bits := Mux1H(
        (0 until p.memoryEntries).map(i =>
            (owners.io.deq.bits === i.U) -> slots(i).io.fastLoadPreview.bits))
    for ((slot, i) <- slots.zipWithIndex) {
        slot.io.fastLoadRetire := io.fastLoadRetire && owners.io.deq.valid && owners.io.deq.bits === i.U
    }
    io.memory.request.valid := requests.io.out.valid && owners.io.enq.ready
    io.memory.request.bits  := requests.io.out.bits
    io.postedProof.foreach { proof =>
        val selectedProof = Mux1H((0 until p.memoryEntries).map(i =>
            (requests.io.chosen === i.U) -> slots(i).io.postedProof.get))
        proof := selectedProof
        proof.valid := io.memory.request.valid && selectedProof.valid
        PostedStoreCpu.held(io.memory.request, proof)
    }
    io.canonicalStoreOrigin.foreach { origin =>
        val selected = Mux1H((0 until p.memoryEntries).map(i =>
            (requests.io.chosen === i.U) -> slots(i).io.canonicalStoreOrigin.get))
        origin := selected
        origin.valid := io.memory.request.valid && selected.valid
        CanonicalVirtualStore.held(io.memory.request, origin)
    }
    requests.io.out.ready   := io.memory.request.ready && owners.io.enq.ready
    owners.io.enq.valid     := io.memory.request.fire
    owners.io.enq.bits      := requests.io.chosen
    when(io.memory.request.valid && !io.memory.request.ready) {
        locked      := true.B
        lockedIndex := requests.io.chosen
    }
    when(io.memory.request.fire) { locked := false.B }
    io.memory.response.ready := owners.io.deq.valid && Mux1H(
        (0 until p.memoryEntries).map(i => (owners.io.deq.bits === i.U) -> slots(i).io.memory.response.ready)
    )
    owners.io.deq.ready := io.memory.response.fire
    for ((slot, i) <- slots.zipWithIndex) {
        slot.io.memory.response.valid := io.memory.response.valid && owners.io.deq.valid && owners.io.deq.bits === i.U
        slot.io.memory.response.bits  := io.memory.response.bits
    }
}
