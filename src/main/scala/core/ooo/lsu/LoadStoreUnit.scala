package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.isa.MCause

// Keep the public CPU-local type names while sharing the exact wire format.
class DataRequest(returnHandleBits: Int = 0) extends soc.ip.memory.NativeMemoryRequest(returnHandleBits)
class DataResponse(returnHandleBits: Int = 0) extends soc.ip.memory.NativeMemoryResponse(returnHandleBits)

/** Each accepted request produces exactly one actual response. The default untagged port requires request order.
  * A configured CPU return handle permits only the qualified completed-store exception; every consumer must recognize
  * exact reservations, and ordered domains retain their drain boundaries. Overlapping reads must observe a
  * nondecreasing memory version in request order, including external writes; tags alone do not establish this.
  */
class DataPort(returnHandleBits: Int = 0) extends Bundle {
    val request  = Decoupled(new DataRequest(returnHandleBits))
    val response = Flipped(Decoupled(new DataResponse(returnHandleBits)))
}
class StoreForward(p: OooParams) extends Bundle {
    val token   = new RobToken(p)
    val address = UInt(64.W)
    val size    = UInt(2.W)
    val data    = UInt(64.W)
}
class MemoryOperation(p: OooParams) extends Bundle {
    val forward  = Valid(UInt(64.W)) // Full aligned beat, only after an older RAM store succeeds.
    val token    = new RobToken(p)
    val pc       = UInt(64.W)
    val address  = UInt(64.W)
    val data     = UInt(64.W)
    val atomic   = Bool()
    val atomicOp = UInt(5.W)
    val store    = Bool()
    val size     = UInt(2.W)
    val unsigned = Bool()
    val accessDenied = Bool()
    val virtualized = Bool()
    val precheckedLoad = Bool()
    val physicalAddress = UInt(64.W)
    val translationEpoch = UInt(32.W)
    val postedProof = p.postedProofConfig.map(c => Valid(new PostedStoreProof(c)))
    // No independent handshake or retained credit: authority belongs to this accepted load.
    val canonicalForward = if (p.completedCanonicalStoreForwarding)
        Some(Valid(new CanonicalStoreCertificate(p))) else None
    val canonicalStoreEpoch = if (p.canonicalVirtualStoreOverlap) Some(Valid(UInt(32.W))) else None
    val frozenStoreProof = if (p.frozenStoreProofEnabled) Some(Valid(new FrozenStoreProof)) else None
}

/** Single-outstanding LSU with cancellable, side-effect-free RAM reads. See docs/bare-core-ipc.md for cycle/side-effect
  * contract.
  */
class LoadStoreUnit(
    p: OooParams,
    registerStart: Boolean = false,
    val responseStateOnly: Boolean = false,
    val orderedResponseReady: Boolean = false
) extends Module {
    require(!responseStateOnly || (p.taggedStoreReturns && p.localTaggedResponseReady && !registerStart),
        "response-state-only LSU requires its registered tagged Parallel owner")
    require(!orderedResponseReady || (p.orderedLsuResponseReady && !registerStart &&
        !responseStateOnly && !p.taggedStoreReturns && p.registeredMemoryRequests && p.bufferedRamStores),
        "ordered readiness specialization is only for integer slots behind registered ordered owners")
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
    // The tagged parent delivers VALID only for an existing registered pending
    // owner. Request acceptance creates that reservation at the clock edge, so
    // neither a new start nor request-state issue can receive an immediate reply.
    // The ordered specialization changes only readiness, not capture/start/result/publication.
    // Its non-flow owner and upstream registered request FIFO preclude a same-cycle new-owner reply.
    io.memory.response.ready := (if (responseStateOnly || orderedResponseReady) state === response else
        state === response || (state === request && io.memory.request.ready) || startRequest)
    if (responseStateOnly) {
        when(io.memory.response.valid) {
            assert(state === response,
                "response-state-only LSU received a reply without its saved response owner")
            assert(!io.start.fire && !io.memory.request.fire,
                "saved tagged response cannot coincide with this slot's new owner or request")
        }
    }
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
    val savedResponseFire = if (responseStateOnly) io.memory.response.fire else io.memory.response.fire && !startRequest
    when(savedResponseFire) {
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
            if (p.completedCanonicalStoreForwarding) {
                assert(p.virtualRamLoadPrecheck.B && io.start.bits.virtualized &&
                    !io.start.bits.store && !io.start.bits.atomic &&
                    (!io.start.bits.forward.valid || io.start.bits.canonicalForward.get.valid),
                    "prechecked physical authorization requires an ordinary virtual load or exact completed-store forwarding")
            } else {
                assert(p.virtualRamLoadPrecheck.B && io.start.bits.virtualized &&
                    !io.start.bits.store && !io.start.bits.atomic && !io.start.bits.forward.valid,
                    "prechecked physical authorization belongs only to an ordinary virtual RAM load")
            }
            assert(io.start.bits.address(11, 0) === io.start.bits.physicalAddress(11, 0),
                "translation preserves the page offset used for lane extraction and precise tval")
            if (p.boundHeadStoreOverlap) {
                assert(!io.start.bits.accessDenied &&
                    AlignedMemoryDisjoint.aligned(io.start.bits.physicalAddress, io.start.bits.size) &&
                    SpeculativeRamRange.contains(p, io.start.bits.physicalAddress, io.start.bits.size),
                    "a saved successful precheck retains an aligned complete RAM byte interval")
            }
        }
        io.start.bits.canonicalForward.foreach { proof =>
            when(io.start.bits.precheckedLoad && io.start.bits.forward.valid) {
                assert(proof.valid, "virtual forwarding requires a checked canonical source certificate")
            }
            when(proof.valid) {
                val store = proof.bits
                assert(io.start.bits.precheckedLoad && io.start.bits.forward.valid &&
                    io.start.bits.virtualized && !io.start.bits.store && !io.start.bits.atomic &&
                    !io.start.bits.accessDenied &&
                    AlignedMemoryDisjoint.aligned(io.start.bits.address, io.start.bits.size) &&
                    AlignedMemoryDisjoint.aligned(io.start.bits.physicalAddress, io.start.bits.size) &&
                    SpeculativeRamRange.contains(p, io.start.bits.physicalAddress, io.start.bits.size),
                    "canonical forwarding consumes an aligned read-authorized ordinary RAM load")
                assert(state === done && operation.store && !operation.atomic && operation.virtualized &&
                    !result.exception && !discard && io.complete.fire &&
                    store.origin.token.asUInt === operation.token.asUInt &&
                    store.virtualAddress === operation.address && store.size === operation.size &&
                    operation.canonicalStoreEpoch.get.valid &&
                    store.origin.epoch === operation.canonicalStoreEpoch.get.bits &&
                    store.origin.epoch === io.start.bits.translationEpoch &&
                    store.origin.token.asUInt =/= io.start.bits.token.asUInt &&
                    io.start.bits.forward.bits === io.forwardStore.bits.data &&
                    CompletedCanonicalStoreForwarding.storeShape(p, store) &&
                    CompletedCanonicalStoreForwarding.covers(store, io.start.bits.physicalAddress, io.start.bits.size),
                    "canonical forwarding replaces the same successful completed store with exact owner epoch and bytes")
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
            done, if (registerStart) request else if (responseStateOnly)
                Mux(io.memory.request.fire, response, request)
            else Mux(io.memory.response.fire, Mux(io.fastStoreRetire, idle, done),
                Mux(io.memory.request.fire, response, request)))
        if (!responseStateOnly) {
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
            val finalException = if (responseStateOnly) staticException else Mux(io.memory.response.fire,
                io.memory.response.bits.error || io.memory.response.bits.pageFault, staticException)
            val finalDone = if (responseStateOnly) staticException || io.start.bits.forward.valid else
                staticException || io.start.bits.forward.valid || (!registerStart.B && io.memory.response.fire)
            capture := !io.start.bits.store && !io.start.bits.atomic && finalDone && !finalException &&
                !io.fastStoreRetire
        }
        assert(!io.start.bits.forward.valid || (!io.start.bits.store && !io.start.bits.atomic))

    }

}
