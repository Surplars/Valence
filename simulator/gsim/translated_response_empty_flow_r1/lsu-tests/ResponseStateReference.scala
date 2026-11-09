package soc.core.ooo
import chisel3._
import chisel3.util._
import soc.isa.MCause
class ResponseStateReferenceLoadStoreUnit(p: OooParams, registerStart: Boolean = false) extends Module {
    val io = IO(new Bundle {
        // State-only reservation hint; start.ready additionally authorizes replacement of the old result.
        val issueAvailable = Output(Bool())
        val successfulLoadResultCapture = if (p.registeredLoadResultReady) Some(Output(Bool())) else None
        val start          = Flipped(Decoupled(new MemoryOperation(p)))
        val memory         = new DataPort
        val postedProof = p.postedProofConfig.map(c => Output(Valid(new PostedStoreProof(c))))
        val canonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap)
            Some(Output(Valid(new CanonicalStoreOrigin(p)))) else None
        val frozenStoreProof = if (p.frozenStoreProofEnabled) Some(Output(Valid(new FrozenStoreProof))) else None
        val complete       = Decoupled(new BackendCompletion(p))
        val busy           = Output(Bool())
        val phase          = Output(UInt(2.W))
        val cancel         = Input(Bool())
        val fastStoreRetire = Input(Bool())
        val fastLoadRetire = Input(Bool())
        val fastLoadPreview = Output(Valid(new BackendCompletion(p)))
        val owner          = Output(new RobToken(p))
        val savedLoadDisjointFromFrozenStart = if (p.boundHeadStoreOverlap) Some(Output(Bool())) else None
        val discarded      = Output(Bool())
        val forwardStore   = Output(Valid(new StoreForward(p)))
        val forwarded      = Output(Bool())
    })
    val idle :: request :: response :: done :: Nil = Enum(4)
    val state                                      = RegInit(idle)
    val operation                                  = Reg(new MemoryOperation(p))
    val result                                     = Reg(new BackendCompletion(p))
    val cancelled                                  = RegInit(false.B)
    val discard                                    = cancelled || io.cancel
    io.successfulLoadResultCapture.foreach(_ := false.B)
    io.owner     := operation.token
    io.discarded := state === done && discard
    when(io.cancel && state =/= idle) {
        assert(!operation.store && !operation.atomic, "an irrevocable store cannot be cancelled")
        cancelled := true.B
    }
    val byteMask    = MuxLookup(io.start.bits.size, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    val atomicWrite = io.start.bits.atomic && io.start.bits.atomicOp =/= 2.U
    val atomicFault = io.start.bits.atomic && !io.start.bits.virtualized &&
        !SpeculativeRamRange.contains(p, io.start.bits.address, io.start.bits.size)
    val misaligned = (io.start.bits.address(2, 0) & byteMask) =/= 0.U
    io.forwardStore.valid        := state === done && operation.store && !result.exception
    io.forwardStore.bits.token   := operation.token
    io.forwardStore.bits.address := operation.address
    io.forwardStore.bits.size    := operation.size
    io.forwardStore.bits.data    := operation.data << Cat(operation.address(2, 0), 0.U(3.W))
    io.forwarded                 := io.start.fire && io.start.bits.forward.valid && !misaligned &&
        !io.start.bits.accessDenied
    io.busy                      := state =/= idle
    io.phase                     := state
    io.issueAvailable            := state === idle || (state === done && !cancelled)
    io.savedLoadDisjointFromFrozenStart.foreach { compatible =>
        val frozen = io.start.bits.frozenStoreProof.get
        val epoch = io.start.bits.canonicalStoreEpoch.get
        // All co-owner facts are the immutable saved operation and registered
        // cancellation. A response error, completion READY or same-edge cancel
        // must not enter the reservation cone. The backend blocks recovery starts.
        // In the restricted B′ integration, a noncancelled busy load has not yet
        // completed to the ROB and cannot have retired or reused its full token.
        // With the proposed exact head at age zero, a different live index is younger.
        compatible := state =/= idle && !cancelled && operation.precheckedLoad && operation.virtualized &&
            !operation.store && !operation.atomic && !operation.forward.valid && !operation.accessDenied &&
            operation.token.index =/= io.start.bits.token.index && frozen.valid && epoch.valid &&
            operation.translationEpoch === epoch.bits &&
            AlignedMemoryDisjoint.withLanes(operation.physicalAddress,
                AlignedMemoryDisjoint.aligned(operation.physicalAddress, operation.size),
                AlignedMemoryDisjoint.lanes(operation.physicalAddress, operation.size),
                frozen.bits.physicalAddress(63, 3), frozen.bits.mask)
    }
    // A same-cycle cancel refers to the old owner. New ownership can replace a completed
    // slot; the backend suppresses new starts on recovery, so cancel need not feed start.ready.
    io.start.ready               := state === idle || (state === done && io.complete.ready && !cancelled)
    // Same-cycle cancellation is rejected by ROB token authorization. Do not feed cancel back into
    // completion arbitration: that arbitration also selects the branch producing cancel.
    io.complete.valid := state === done && !cancelled
    io.complete.bits  := result
    // Start and memory request can handshake together. Only registered slot state controls
    // start readiness; a stalled memory port leaves the accepted operation in request state.
    // A registered client captures permissions and the complete operation on
    // start.fire. Neither the new payload nor its fault decision can bypass
    // that boundary into request.bits/response.ready. Legacy integer clients
    // retain their measured same-cycle buffered-store contract.
    val startRequest = if (registerStart) false.B else io.start.fire && !misaligned && !atomicFault &&
        !io.start.bits.accessDenied && !io.start.bits.forward.valid
    val sending = Mux(startRequest, io.start.bits, operation)
    val shift = Cat(sending.address(2, 0), 0.U(3.W))
    val mask  = MuxLookup(sending.size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
    io.memory.request.valid         := state === request || startRequest
    io.memory.request.bits.atomic   := sending.atomic
    io.memory.request.bits.atomicOp := sending.atomicOp
    io.memory.request.bits.address  := Mux(sending.precheckedLoad, sending.physicalAddress, sending.address)
    io.memory.request.bits.write    := sending.store
    io.memory.request.bits.size     := sending.size
    io.memory.request.bits.data     := Mux(sending.atomic, sending.data, sending.data << shift)
    io.memory.request.bits.mask     := mask << sending.address(2, 0)
    io.memory.request.bits.virtualized := sending.virtualized && !sending.precheckedLoad
    io.memory.request.bits.precheckedLoad := sending.precheckedLoad
    io.memory.request.bits.translationEpoch := sending.translationEpoch
    io.memory.request.bits.uncached := false.B
    io.memory.request.bits.prefetchNextAllowed := false.B
    io.postedProof.foreach { proof =>
        proof := sending.postedProof.get
        proof.valid := io.memory.request.valid && sending.postedProof.get.valid
        PostedStoreCpu.held(io.memory.request, proof)
        when(io.start.fire && io.start.bits.postedProof.get.valid) {
            assert(!misaligned && !atomicFault && !io.start.bits.accessDenied &&
                !io.start.bits.forward.valid && !io.start.bits.virtualized &&
                io.start.bits.store && !io.start.bits.atomic, "posted authority belongs to a successful physical store")
            assert(io.start.bits.postedProof.get.bits.token.asUInt === io.start.bits.token.asUInt)
        }
    }
    io.canonicalStoreOrigin.foreach { origin =>
        origin.valid := io.memory.request.valid && sending.canonicalStoreEpoch.get.valid
        origin.bits.token := sending.token
        origin.bits.epoch := sending.canonicalStoreEpoch.get.bits
        CanonicalVirtualStore.held(io.memory.request, origin)
        when(io.start.fire && io.start.bits.canonicalStoreEpoch.get.valid) {
            assert(io.start.bits.virtualized && io.start.bits.store && !io.start.bits.atomic &&
                !io.start.bits.precheckedLoad && !io.start.bits.forward.valid &&
                !misaligned && !io.start.bits.accessDenied,
                "canonical origin belongs to an accepted ordinary virtual store")
        }
    }
    io.frozenStoreProof.foreach { proof =>
        proof := sending.frozenStoreProof.get
        proof.valid := io.memory.request.valid && sending.frozenStoreProof.get.valid
        CanonicalVirtualStore.heldFrozen(p, io.memory.request, io.canonicalStoreOrigin.get, proof)
        when(io.start.fire && io.start.bits.frozenStoreProof.get.valid) {
            assert(io.start.bits.canonicalStoreEpoch.get.valid && !io.start.bits.forward.valid &&
                !io.start.bits.accessDenied && !misaligned && !atomicFault,
                "a frozen binding transfers only with its successful real virtual-store start")
            io.start.bits.postedProof.foreach(posted => assert(!posted.valid,
                "frozen virtual-store proof cannot grant posted-store authority"))
        }
    }
    io.memory.response.ready        := state === response ||
        (state === request && io.memory.request.ready) || startRequest
    when(io.memory.request.fire) { state := response }
    def loadValue(beat: UInt, address: UInt, size: UInt, unsigned: Bool): UInt = {
        val shifted = beat >> Cat(address(2, 0), 0.U(3.W))
        MuxLookup(size, shifted)(
            Seq(
                0.U -> Cat(Fill(56, !unsigned && shifted(7)), shifted(7, 0)),
                1.U -> Cat(Fill(48, !unsigned && shifted(15)), shifted(15, 0)),
                2.U -> Cat(Fill(32, !unsigned && shifted(31)), shifted(31, 0))
            )
        )
    }
    val loaded = loadValue(io.memory.response.bits.data, operation.address, operation.size, operation.unsigned)
    io.fastLoadPreview.valid := state === response && io.memory.response.valid && !discard &&
        !operation.store && !operation.atomic && !io.memory.response.bits.error &&
        !io.memory.response.bits.pageFault
    io.fastLoadPreview.bits := result
    io.fastLoadPreview.bits.data := loaded
    io.fastLoadPreview.bits.exception := false.B
    when(io.memory.response.fire && !startRequest) {
        result.data      := Mux(operation.atomic, io.memory.response.bits.data, Mux(operation.store, 0.U, loaded))
        result.exception := io.memory.response.bits.error || io.memory.response.bits.pageFault
        val writeAccess = operation.store || (operation.atomic && operation.atomicOp =/= 2.U)
        result.cause := Mux(io.memory.response.bits.pageFault,
            Mux(writeAccess, MCause.StorePageFault, MCause.LoadPageFault),
            Mux(writeAccess, MCause.StoreAccessFault, MCause.LoadAccessFault))
        state := Mux(io.fastLoadRetire, idle, done)
        io.successfulLoadResultCapture.foreach(_ := !operation.store && !operation.atomic &&
            !discard && !io.memory.response.bits.error && !io.memory.response.bits.pageFault &&
            !io.fastLoadRetire)
    }
    when(io.fastLoadRetire) {
        assert(io.fastLoadPreview.valid && io.memory.response.fire,
            "fast load retirement requires a successful existing load response")
    }
    when(io.complete.fire || (state === done && discard)) {
        state := idle
        io.successfulLoadResultCapture.foreach(_ := false.B)
    }
    // New ownership wins over freeing the result accepted in the same cycle.
    when(io.start.fire) {
        when(io.start.bits.precheckedLoad) {
            assert(p.virtualRamLoadPrecheck.B && io.start.bits.virtualized &&
                !io.start.bits.store && !io.start.bits.atomic && !io.start.bits.forward.valid,
                "prechecked physical authorization belongs only to an ordinary virtual RAM load")
            assert(io.start.bits.address(11, 0) === io.start.bits.physicalAddress(11, 0),
                "translation preserves the page offset used for lane extraction and precise tval")
            if (p.boundHeadStoreOverlap) {
                assert(!io.start.bits.accessDenied &&
                    AlignedMemoryDisjoint.aligned(io.start.bits.physicalAddress, io.start.bits.size) &&
                    SpeculativeRamRange.contains(p, io.start.bits.physicalAddress, io.start.bits.size),
                    "a saved successful precheck retains an aligned complete RAM byte interval")
            }
        }
        cancelled        := false.B
        operation        := io.start.bits
        result           := 0.U.asTypeOf(new BackendCompletion(p))
        result.token     := io.start.bits.token
        result.nextPc    := io.start.bits.pc + 4.U
        result.exception := misaligned || atomicFault || io.start.bits.accessDenied
        result.cause     := Mux(
            misaligned,
            Mux(io.start.bits.store || atomicWrite, MCause.StoreAddrMisaligned, MCause.LoadAddrMisaligned),
            Mux(io.start.bits.accessDenied,
                Mux(io.start.bits.store || atomicWrite, MCause.StoreAccessFault, MCause.LoadAccessFault),
                Mux(atomicWrite, MCause.StoreAccessFault, MCause.LoadAccessFault))
        )
        result.tval := io.start.bits.address
        result.data := Mux(
            io.start.bits.forward.valid,
            loadValue(io.start.bits.forward.bits, io.start.bits.address, io.start.bits.size, io.start.bits.unsigned),
            0.U
        )
        state := Mux(misaligned || atomicFault || io.start.bits.accessDenied || io.start.bits.forward.valid,
            done, if (registerStart) request else Mux(io.memory.response.fire,
                Mux(io.fastStoreRetire, idle, done),
                Mux(io.memory.request.fire, response, request)))
        when(io.memory.response.fire) {
            val immediate = io.memory.response.bits
            result.data := Mux(io.start.bits.atomic, immediate.data,
                Mux(io.start.bits.store, 0.U,
                    loadValue(immediate.data, io.start.bits.address, io.start.bits.size, io.start.bits.unsigned)))
            result.exception := immediate.error || immediate.pageFault
            val writeAccess = io.start.bits.store || (io.start.bits.atomic && io.start.bits.atomicOp =/= 2.U)
            result.cause := Mux(immediate.pageFault,
                Mux(writeAccess, MCause.StorePageFault, MCause.LoadPageFault),
                Mux(writeAccess, MCause.StoreAccessFault, MCause.LoadAccessFault))
        }
        when(io.fastStoreRetire) {
            assert(!registerStart.B, "registered LSU cannot retire a new store in its capture cycle")
            assert(io.start.bits.store && !io.start.bits.atomic && io.memory.request.fire &&
                io.memory.response.fire && !io.memory.response.bits.error &&
                !io.memory.response.bits.pageFault && !misaligned && !atomicFault &&
                !io.start.bits.accessDenied,
                "fast store retirement requires a successful same-cycle buffered response")
        }
        io.successfulLoadResultCapture.foreach { capture =>
            // This writer has the same final priority as new result ownership.
            // A new owner's cancellation state is clear, independent of the old owner.
            val staticException = misaligned || atomicFault || io.start.bits.accessDenied
            val finalException = Mux(io.memory.response.fire,
                io.memory.response.bits.error || io.memory.response.bits.pageFault, staticException)
            val finalDone = staticException || io.start.bits.forward.valid ||
                (!registerStart.B && io.memory.response.fire)
            capture := !io.start.bits.store && !io.start.bits.atomic && finalDone && !finalException &&
                !io.fastStoreRetire
        }
        assert(!io.start.bits.forward.valid || (!io.start.bits.store && !io.start.bits.atomic))

    }

}

class ResponseStateReferenceParallelLoadStoreUnit(
    p: OooParams,
    canonicalHandoff: Boolean = false,
    val localTaggedResponseReady: Boolean = false
) extends Module {
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
    val slots      = Seq.fill(p.memoryEntries)(Module(new ResponseStateReferenceLoadStoreUnit(p)))
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
    val exemptSerial = (0 until p.memoryEntries).map { i =>
        io.relaxStoreOwner.map(owner => owner.valid && ordinaryPrechecked && io.parallel &&
            slots(i).io.busy && !parallel(i) && requestAccepted.get(i) && certifiedStoreClass.get(i) &&
            owner.bits.asUInt === slots(i).io.owner.asUInt).getOrElse(false.B)
    }
    // A certified store may be waiting for completion arbitration while another
    // physical slot is empty. Its exact registered authorization already permits
    // this prechecked load; do not force it to replace the blocked completion.
    // Never feed completion READY or cancellation into the reservation selector.
    val handoffOffer = if (canonicalHandoff) empty.asUInt.orR && exemptSerial.reduce(_ || _) else false.B
    val boundHeadStoreOverlapOffer = io.boundHeadStoreOverlapQualified.map { qualified =>
        qualified && !io.parallel && empty.asUInt.orR && io.busy &&
            (0 until p.memoryEntries).map(i => !slots(i).io.busy ||
                (parallel(i) && slots(i).io.savedLoadDisjointFromFrozenStart.get)).reduce(_ && _)
    }.getOrElse(false.B)
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
