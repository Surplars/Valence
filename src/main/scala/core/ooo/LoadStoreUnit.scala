package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.isa.MCause

class DataRequest extends Bundle {
    val atomic   = Bool()
    val atomicOp = UInt(5.W)
    val address  = UInt(64.W) // Effective byte address, not aligned down.
    val write    = Bool()
    val size     = UInt(2.W)  // log2(bytes)
    val data     = UInt(64.W) // Ordinary stores use aligned beat lanes; atomic rs2 is right-justified.
    val mask     = UInt(8.W)
    val virtualized = Bool() // Address has not yet been translated; only the core's VM adapter consumes it.
    val precheckedLoad = Bool() // Frozen PA from the hit-only virtual-load authorization path.
    val translationEpoch = UInt(32.W) // Consumed and cleared at the physical authorization adapter.
    val prefetchNextAllowed = Bool() // Full next-line permission captured by the physical authorization adapter.
    val uncached = Bool() // Physical access must bypass the private cache (for example, PBMT NC/IO).
}
class DataResponse extends Bundle {
    val data  = UInt(64.W) // Ordinary loads return a beat; atomics return the complete XLEN result.
    val error = Bool()     // An errored write must have no memory side effect.
    val pageFault = Bool() // An address-translation fault, distinct from a physical access error.
}

/** Each accepted request produces exactly one response, in request-handshake order. No transaction IDs: an integrating
  * cache/bus adapter must restore order before this port. Overlapping reads must observe a nondecreasing memory version
  * in request order, including external writes; response reordering alone does not satisfy this contract.
  */
class DataPort extends Bundle {
    val request  = Decoupled(new DataRequest)
    val response = Flipped(Decoupled(new DataResponse))
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
}

/** Single-outstanding LSU with cancellable, side-effect-free RAM reads. See docs/bare-core-ipc.md for cycle/side-effect
  * contract.
  */
class LoadStoreUnit(p: OooParams, registerStart: Boolean = false) extends Module {
    val io = IO(new Bundle {
        // State-only reservation hint; start.ready additionally authorizes replacement of the old result.
        val issueAvailable = Output(Bool())
        val start          = Flipped(Decoupled(new MemoryOperation(p)))
        val memory         = new DataPort
        val complete       = Decoupled(new BackendCompletion(p))
        val busy           = Output(Bool())
        val phase          = Output(UInt(2.W))
        val cancel         = Input(Bool())
        val fastStoreRetire = Input(Bool())
        val fastLoadRetire = Input(Bool())
        val fastLoadPreview = Output(Valid(new BackendCompletion(p)))
        val owner          = Output(new RobToken(p))
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
    }
    when(io.fastLoadRetire) {
        assert(io.fastLoadPreview.valid && io.memory.response.fire,
            "fast load retirement requires a successful existing load response")
    }
    when(io.complete.fire || (state === done && discard)) { state := idle }
    // New ownership wins over freeing the result accepted in the same cycle.
    when(io.start.fire) {
        when(io.start.bits.precheckedLoad) {
            assert(p.virtualRamLoadPrecheck.B && io.start.bits.virtualized &&
                !io.start.bits.store && !io.start.bits.atomic && !io.start.bits.forward.valid,
                "prechecked physical authorization belongs only to an ordinary virtual RAM load")
            assert(io.start.bits.address(11, 0) === io.start.bits.physicalAddress(11, 0),
                "translation preserves the page offset used for lane extraction and precise tval")
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
        assert(!io.start.bits.forward.valid || (!io.start.bits.store && !io.start.bits.atomic))

    }

}
