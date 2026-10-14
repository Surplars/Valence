package soc.core.ooo

import chisel3._
import chisel3.util._

/** Bounded RAM read concurrency. Replies are ordered by default, or matched to
  * nonreused slot reservations by the optional CPU return protocol.
  */
class ParallelLoadStoreUnit(
    p: OooParams,
    canonicalHandoff: Boolean = false,
    val localTaggedResponseReady: Boolean = false,
    val candidateLoadPreparation: Boolean = false
) extends Module {
    def this(p: OooParams, handoff: Boolean, localReady: Boolean) = this(p, handoff, localReady, false)
    require(!candidateLoadPreparation || (p.pendingVirtualStoreProof && !p.memoryProofFrontier),
        "candidate load admission requires the final-flush-protected pending-proof topology")
    require(localTaggedResponseReady == p.localTaggedResponseReady,
        "tagged readiness constructor must use the unified OooParams flag")
    require(!localTaggedResponseReady || p.taggedStoreReturns,
        "local response readiness requires registered, nonreused tagged LSU reservations")
    require(!canonicalHandoff || (p.canonicalVirtualStoreOverlap && p.virtualRamLoadPrecheck))
    private val indexBits = math.max(1, log2Ceil(p.memoryEntries))
    val io                = IO(new Bundle {
        val start          = Flipped(Decoupled(new MemoryOperation(p)))
        // Sideband belongs to the accepted start owner, never a ROB lookup at completion.
        val issueDestination = if (p.registeredLoadIssueForwarding)
            Some(Input(Valid(UInt(p.physBits.W)))) else None
        val completedIssueDestination = if (p.registeredLoadIssueForwarding)
            Some(Output(Valid(UInt(p.physBits.W)))) else None
        val loadResultPublish = if (p.registeredLoadResultReady)
            Some(Output(Vec(p.memoryEntries, Valid(UInt(p.physBits.W))))) else None
        val heldLoadValue = if (p.registeredLoadResultReady) Some(Output(Vec(p.memoryEntries, Valid(new Bundle {
            val destination = UInt(p.physBits.W)
            val data = UInt(64.W)
        })))) else None
        val parallel       = Input(Bool())
        val issueAvailable = Output(Bool())
        val candidateAdmission = if (candidateLoadPreparation) Some(Input(new Bundle {
            val precheckedLoad = Bool()
            val parallel = Bool()
        })) else None
        val candidateIssueAvailable = if (candidateLoadPreparation) Some(Output(Bool())) else None
        val boundHeadStoreOverlapQualified = if (p.boundHeadStoreOverlap) Some(Input(Bool())) else None
        // Assertion/test witness only; never feeds reservation or ownership.
        val boundHeadStoreOverlapAccepted = if (p.boundHeadStoreOverlap) Some(Output(Bool())) else None
        val acceptedStartSlot = if (p.memoryProofFrontier) Some(Output(Valid(UInt(indexBits.W)))) else None
        val memory         = new DataPort(p.dataReturnHandleBits)
        val postedProof = p.postedProofConfig.map(c => Output(Valid(new PostedStoreProof(c))))
        val canonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap)
            Some(Output(Valid(new CanonicalStoreOrigin(p)))) else None
        val frozenStoreProof = if (p.frozenStoreProofEnabled) Some(Output(Valid(new FrozenStoreProof))) else None
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
    val slots      = Seq.fill(p.memoryEntries)(Module(new LoadStoreUnit(p, responseStateOnly = localTaggedResponseReady)))
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
        if (p.registeredLoadResultReady) {
            for ((slot, i) <- slots.zipWithIndex) {
                // A registered tagged reservation can deliver only to a response-state
                // owner. Its successful result does not depend on another slot's new
                // request arbitration. Forwarded starts are the only new-owner result.
                val capture = if (localTaggedResponseReady) {
                    val responseCapture = slot.io.fastLoadPreview.valid && !slot.io.fastLoadRetire
                    val forwardedCapture = slot.io.forwarded && !slot.io.start.bits.store &&
                        !slot.io.start.bits.atomic && !slot.io.fastStoreRetire
                    responseCapture || forwardedCapture
                } else slot.io.successfulLoadResultCapture.get
                // On a valid publication the saved response owner and accepted new
                // owner are mutually exclusive. Select their IDs from registered phase,
                // before the final event validity, rather than from late start.fire.
                val publishingDestination = if (localTaggedResponseReady)
                    Mux(slot.io.phase === 2.U, owners(i), io.issueDestination.get)
                else Mux(slot.io.start.fire, io.issueDestination.get, owners(i))
                io.loadResultPublish.get(i).valid := capture &&
                    publishingDestination.valid && publishingDestination.bits =/= 0.U
                io.loadResultPublish.get(i).bits := publishingDestination.bits
                io.heldLoadValue.get(i).valid := slot.io.complete.valid &&
                    !slot.io.complete.bits.exception && owners(i).valid
                io.heldLoadValue.get(i).bits.destination := owners(i).bits
                io.heldLoadValue.get(i).bits.data := slot.io.complete.bits.data
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
    val ordinaryPrechecked = io.start.bits.precheckedLoad && io.start.bits.virtualized &&
        !io.start.bits.store && !io.start.bits.atomic && !io.start.bits.forward.valid
    // Match the retained store owner once; strict and candidate views differ only
    // in two Boolean qualifications, never in the wide owner comparison.
    val exemptOwner = (0 until p.memoryEntries).map { i =>
        io.relaxStoreOwner.map(owner => owner.valid &&
            slots(i).io.busy && !parallel(i) && requestAccepted.get(i) && certifiedStoreClass.get(i) &&
            owner.bits.asUInt === slots(i).io.owner.asUInt).getOrElse(false.B)
    }
    val exemptSerial = exemptOwner.map(_ && ordinaryPrechecked && io.parallel)
    // A certified store may be waiting for completion arbitration while another
    // physical slot is empty. Its exact registered authorization already permits
    // this prechecked load; do not force it to replace the blocked completion.
    // Never feed completion READY or cancellation into the reservation selector.
    val handoffOffer = if (canonicalHandoff) empty.asUInt.orR && exemptSerial.reduce(_ || _) else false.B
    val boundHeadStoreOverlapCommon = io.boundHeadStoreOverlapQualified.map { qualified =>
        qualified && empty.asUInt.orR && io.busy &&
            (0 until p.memoryEntries).map(i => !slots(i).io.busy ||
                (parallel(i) && slots(i).io.savedLoadDisjointFromFrozenStart.get)).reduce(_ && _)
    }.getOrElse(false.B)
    val boundHeadStoreOverlapOffer = boundHeadStoreOverlapCommon && !io.parallel
    val emptyChoice = PriorityEncoder(empty)
    val baseChosen = Mux(handoffOffer, emptyChoice,
        Mux(completion.io.out.valid, completion.io.chosen, emptyChoice))
    val chosen = Mux(boundHeadStoreOverlapOffer, emptyChoice, baseChosen)
    val available = completion.io.out.valid || empty.asUInt.orR
    val othersIdle = (0 until p.memoryEntries).map(i => baseChosen === i.U || !slots(i).io.busy).reduce(_ && _)
    val observationCanonicalHandoff = WireDefault(io.start.fire && handoffOffer)
    val noOtherSerial = (0 until p.memoryEntries)
        .map(i => !slots(i).io.busy || parallel(i) || (completion.io.out.valid && baseChosen === i.U) || exemptSerial(i))
        .reduce(_ && _)
    // The bound-store offer already proves an empty slot and that every live
    // co-owner is parallel. It therefore implies available and noOtherSerial.
    val baseIssueAvailable = available && noOtherSerial && (io.parallel || othersIdle)
    io.issueAvailable := baseIssueAvailable || boundHeadStoreOverlapOffer
    io.start.ready    := io.issueAvailable && Mux1H(
        (0 until p.memoryEntries).map(i => (chosen === i.U) -> slots(i).io.start.ready)
    )
    // Preserve all strict public readiness/profiling values. Only the private
    // new-start gate uses the candidate view; the caller must make both views
    // identical whenever it authorizes start.valid. Existing requests and old
    // responses never depend on this private choice.
    val (admissionAvailable, admissionChosen) = if (candidateLoadPreparation) {
        val candidate = io.candidateAdmission.get
        val ordinary = candidate.precheckedLoad && io.start.bits.virtualized &&
            !io.start.bits.store && !io.start.bits.atomic && !io.start.bits.forward.valid
        val exempt = exemptOwner.map(_ && ordinary && candidate.parallel)
        val handoff = if (canonicalHandoff) empty.asUInt.orR && exempt.reduce(_ || _) else false.B
        val base = Mux(handoff, emptyChoice,
            Mux(completion.io.out.valid, completion.io.chosen, emptyChoice))
        val boundOffer = boundHeadStoreOverlapCommon && !candidate.parallel
        val selected = Mux(boundOffer, emptyChoice, base)
        val others = (0 until p.memoryEntries).map(i => base === i.U || !slots(i).io.busy).reduce(_ && _)
        val noSerial = (0 until p.memoryEntries).map(i => !slots(i).io.busy || parallel(i) ||
            (completion.io.out.valid && base === i.U) || exempt(i)).reduce(_ && _)
        val capacity = (available && noSerial && (candidate.parallel || others)) || boundOffer
        io.candidateIssueAvailable.get := capacity
        when(io.start.valid) {
            assert(candidate.precheckedLoad === io.start.bits.precheckedLoad && candidate.parallel === io.parallel,
                "candidate admission may differ only when final permission blocks a new start")
            assert(capacity === io.issueAvailable && selected === chosen,
                "authorized candidate admission retains exact strict capacity and slot selection")
        }
        (capacity, selected)
    } else (io.issueAvailable, chosen)
    when(observationCanonicalHandoff) {
        assert(ordinaryPrechecked && io.parallel && empty(chosen),
            "authorized handoff must use an empty slot without completing or replacing the store")
    }
    io.boundHeadStoreOverlapAccepted.foreach { accepted =>
        accepted := io.start.fire && boundHeadStoreOverlapOffer
        when(accepted) {
            assert(!io.parallel && empty(chosen) && io.start.bits.store && io.start.bits.virtualized &&
                !io.start.bits.atomic && !io.start.bits.forward.valid && !io.start.bits.accessDenied &&
                io.start.bits.frozenStoreProof.get.valid && io.start.bits.canonicalStoreEpoch.get.valid,
                "bound head-store overlap captures only an ordinary frozen serial store in an actually idle slot")
            for (i <- 0 until p.memoryEntries) {
                when(slots(i).io.busy) {
                    assert(parallel(i) && slots(i).io.savedLoadDisjointFromFrozenStart.get && !io.cancel(i),
                        "every pre-edge co-owner must survive the accepted bound-store start")
                }
            }
        }
    }
    io.acceptedStartSlot.foreach { accepted =>
        accepted.valid := io.start.fire
        accepted.bits := chosen
    }
    for ((slot, i) <- slots.zipWithIndex) {
        slot.io.start.valid := io.start.valid && admissionAvailable && admissionChosen === i.U
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

    if (candidateLoadPreparation) {
        assert(VecInit(slots.map(_.io.start.fire)).asUInt.orR === io.start.fire,
            "candidate slot capture must equal the unchanged public parent handshake")
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
    val owners = CpuReturnTransport.ownerView(UInt(indexBits.W), p.memoryEntries)
    p.cpuReturnConfig match {
        case None => CpuReturnTransport.orderedOwners(owners, UInt(indexBits.W), p.memoryEntries, flow = true)
        case Some(config) =>
            val pending = RegInit(VecInit(Seq.fill(p.memoryEntries)(false.B)))
            val handle = io.memory.response.bits.returnHandle.get
            val slot = handle(indexBits - 1, 0)
            owners.io.enq.ready := !pending(requests.io.chosen)
            owners.io.deq.valid := config.integer(handle) && pending(slot)
            owners.io.deq.bits := slot
            owners.io.count := PopCount(pending)
            when(owners.io.enq.fire) { pending(owners.io.enq.bits) := true.B }
            when(io.memory.response.fire) { pending(slot) := false.B }
            if (localTaggedResponseReady) {
                for (i <- 0 until p.memoryEntries) {
                    when(pending(i)) {
                        // LoadStoreUnit's public phase encoding is idle/request/response/done.
                        // Cancellation retains this response responsibility until its real fire.
                        assert(slots(i).io.phase === 2.U,
                            "a pending tagged reservation retains a response-state LSU owner")
                        assert(slots(i).io.memory.response.ready,
                            "registered tagged owner is always ready for its actual response")
                    }
                }
            }
            when(io.memory.response.valid) {
                val entering = io.memory.request.fire && requests.io.chosen === slot
                assert(config.integer(handle) && (pending(slot) || entering),
                    "CPU response lost its exact LSU reservation")
            }
            CpuReturnTransport.held(io.memory.response)
    }
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
    CpuReturnTransport.requestPayload(io.memory.request.bits, requests.io.out.bits)
    io.memory.request.bits.returnHandle.foreach(_ := requests.io.chosen)
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
    io.frozenStoreProof.foreach { proof =>
        val selected = Mux1H((0 until p.memoryEntries).map(i =>
            (requests.io.chosen === i.U) -> slots(i).io.frozenStoreProof.get))
        proof := selected
        proof.valid := io.memory.request.valid && selected.valid
        CanonicalVirtualStore.heldFrozen(p, io.memory.request, io.canonicalStoreOrigin.get, proof)
        when(io.memory.request.valid && proof.valid) {
            assert(io.requestOwner.valid &&
                io.canonicalStoreOrigin.get.bits.token.asUInt === io.requestOwner.bits.asUInt,
                "frozen proof and canonical origin retain the actual selected LSU owner")
        }
    }
    requests.io.out.ready   := io.memory.request.ready && owners.io.enq.ready
    owners.io.enq.valid     := io.memory.request.fire
    owners.io.enq.bits      := requests.io.chosen
    when(io.memory.request.valid && !io.memory.request.ready) {
        locked      := true.B
        lockedIndex := requests.io.chosen
    }
    when(io.memory.request.fire) { locked := false.B }
    // Tagged ownership cannot flow through request acceptance: pending is registered.
    // Its owner therefore waits in response state until this exact response fires.
    // The ordered flow-through topology retains the original slot-ready selection.
    io.memory.response.ready := owners.io.deq.valid && (if (localTaggedResponseReady) true.B else Mux1H(
        (0 until p.memoryEntries).map(i => (owners.io.deq.bits === i.U) -> slots(i).io.memory.response.ready)
    ))
    owners.io.deq.ready := io.memory.response.fire
    for ((slot, i) <- slots.zipWithIndex) {
        slot.io.memory.response.valid := io.memory.response.valid && owners.io.deq.valid && owners.io.deq.bits === i.U
        CpuReturnTransport.responsePayload(slot.io.memory.response.bits, io.memory.response.bits)
    }
}
