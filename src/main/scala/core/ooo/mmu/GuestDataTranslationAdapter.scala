package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.memory.{NativeMemoryPort, NativeMemoryRequest, NativeMemoryResponse}

/** Raw trap provenance, owned by the same response/ROB entry as its fault. */
class GuestFaultMetadata extends Bundle {
    val guestPageFault = Bool()
    val guestAddress = Bool()
    val guestPhysicalAddress = UInt(64.W)
    val implicitPte = Bool()
}

class GuestPhysicalAccess extends Bundle {
    val address = UInt(64.W)
    val size = UInt(2.W)
    val access = UInt(2.W)
    val forceExecute = Bool() // HLVX requires physical PMA read AND execute.
}

/** Experimental single-owner guest data boundary, using the exact DataPort wire
  * format from NativeMemoryPort without depending on the complete LSU class.
  * No prechecked/identity/posted shortcut. Context and payload freeze together
  * on virtual.request.fire. Translation, physical request and actual response
  * remain owned until virtual.response.fire. Capacity=1, no turnover bypass.
  *
  * `cancel` kills only ordinary reads. Accepted writes/atomics are irrevocable
  * committed owners and must drain normally. An already offered read is never
  * withdrawn; its response drains into a cancelled tombstone. Upstream must
  * reject cancelled/stale-epoch responses and serialize side-effecting MMIO.
  * guestFault/cancelled/responseEpoch have exactly virtual.response's lifetime.
  * The external translator must receive translationCancel. PMP is checked by
  * that translator; physicalCheck/pmaDenied provide final PMA authorization.
  */
class GuestDataTranslationAdapter(returnHandleBits: Int = 0) extends Module {
    val io = IO(new Bundle {
        val virtual = Flipped(new NativeMemoryPort(returnHandleBits))
        val physical = new NativeMemoryPort(returnHandleBits)
        val translation = new GuestTranslationPort
        val context = Input(new GuestTranslationRequest)
        val cancel = Input(Bool())
        val translationCancel = Output(Bool())
        val physicalCheck = Output(Valid(new GuestPhysicalAccess))
        val pmaDenied = Input(Bool())
        val guestFault = Output(new GuestFaultMetadata)
        val cancelled = Output(Bool())
        val responseEpoch = Output(UInt(8.W))
        val idle = Output(Bool())
    })
    val Seq(idle, offerTranslation, waitTranslation, checkPhysical, offerPhysical, waitPhysical, reply) = Enum(7)
    val state = RegInit(idle)
    val request = Reg(new NativeMemoryRequest(returnHandleBits))
    val context = Reg(new GuestTranslationRequest)
    val response = RegInit(0.U.asTypeOf(new NativeMemoryResponse(returnHandleBits)))
    val fault = RegInit(0.U.asTypeOf(new GuestFaultMetadata))
    val wasCancelled = RegInit(false.B)
    val killed = RegInit(false.B)
    val cancellable = !request.write && !request.atomic
    val killNow = killed || (io.cancel && cancellable)

    io.idle := state === idle
    io.virtual.request.ready := state === idle && !io.cancel
    io.virtual.response.valid := state === reply
    io.virtual.response.bits := response
    io.guestFault := fault
    io.cancelled := wasCancelled
    io.responseEpoch := context.epoch
    io.translation.request.valid := state === offerTranslation
    io.translation.request.bits := context
    io.translation.response.ready := state === waitTranslation
    // Never block an unaccepted held translation offer with its cancellation.
    io.translationCancel := state === waitTranslation && killNow
    io.physical.request.valid := state === offerPhysical
    io.physical.request.bits := request
    io.physical.response.ready := state === waitPhysical
    io.physicalCheck.valid := state === checkPhysical
    io.physicalCheck.bits.address := request.address
    io.physicalCheck.bits.size := request.size
    io.physicalCheck.bits.access := context.access
    io.physicalCheck.bits.forceExecute := context.forceExecute

    def cancelledReply(): Unit = {
        response.data := 0.U
        response.error := false.B
        response.pageFault := false.B
        fault := 0.U.asTypeOf(new GuestFaultMetadata)
        wasCancelled := true.B
        state := reply
    }
    when(io.virtual.request.fire) {
        request := io.virtual.request.bits
        // Native physical offers never carry stale virtual permission proofs.
        request.virtualized := false.B
        request.precheckedLoad := false.B
        request.translationEpoch := 0.U
        request.prefetchNextAllowed := false.B
        context := io.context
        context.virtualAddress := io.virtual.request.bits.address
        context.size := io.virtual.request.bits.size
        context.access := Mux(io.virtual.request.bits.atomic,
            Mux(io.virtual.request.bits.atomicOp === 2.U, PmpAccess.read,
                Mux(io.virtual.request.bits.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
            Mux(io.virtual.request.bits.write, PmpAccess.write, PmpAccess.read))
        response := 0.U.asTypeOf(new NativeMemoryResponse(returnHandleBits))
        response.returnHandle.foreach(_ := io.virtual.request.bits.returnHandle.get)
        fault := 0.U.asTypeOf(new GuestFaultMetadata)
        fault.guestAddress := io.context.virtualized
        killed := false.B
        wasCancelled := false.B
        state := offerTranslation
        assert(!io.context.forceExecute || (!io.virtual.request.bits.write && !io.virtual.request.bits.atomic),
            "HLVX is an ordinary load, not a write or atomic")
    }
    when(io.translation.request.fire) { state := waitTranslation }
    when(io.translation.response.fire) {
        val translated = io.translation.response.bits
        assert(translated.epoch === context.epoch && translated.virtualAddress === context.virtualAddress,
            "translation response lost its accepted request owner")
        when(translated.cancelled || killNow) { cancelledReply() }
            .otherwise {
                fault.guestAddress := context.virtualized
                fault.guestPageFault := translated.guestPageFault
                fault.guestPhysicalAddress := Mux(translated.guestPageFault, translated.guestPhysicalAddress, 0.U)
                fault.implicitPte := translated.guestPageFault && translated.implicitPte
                when(translated.pageFault || translated.guestPageFault || translated.accessFault) {
                    response.error := true.B
                    response.pageFault := translated.pageFault
                    state := reply
                }.otherwise {
                    request.address := translated.physicalAddress
                    state := checkPhysical
                }
            }
    }
    when(state === checkPhysical) {
        when(killNow) { cancelledReply() }
            .elsewhen(io.pmaDenied) { response.error := true.B; state := reply }
            .otherwise { state := offerPhysical }
    }
    when(io.physical.request.fire) { state := waitPhysical }
    when(io.physical.response.fire) {
        response := io.physical.response.bits
        response.returnHandle.foreach { handle =>
            assert(io.physical.response.bits.returnHandle.get === request.returnHandle.get,
                "physical completion return handle does not name the single owner")
            handle := request.returnHandle.get
        }
        // A physical endpoint cannot originate a VS-stage translation fault.
        assert(!io.physical.response.bits.pageFault, "physical endpoint returned a virtual page fault")
        state := reply
        when(killNow) { cancelledReply() }
    }
    when(state =/= idle && state =/= reply && io.cancel && cancellable) { killed := true.B }
    when(io.virtual.response.fire) { state := idle }

    val heldPhysical = RegNext(io.physical.request.valid && !io.physical.request.ready, false.B)
    val priorPhysical = RegEnable(io.physical.request.bits, io.physical.request.valid && !io.physical.request.ready)
    val heldResponse = RegNext(io.virtual.response.valid && !io.virtual.response.ready, false.B)
    val responseSnapshot = RegEnable(Cat(io.virtual.response.bits.asUInt, io.guestFault.asUInt,
        io.cancelled, io.responseEpoch), io.virtual.response.valid && !io.virtual.response.ready)
    when(!reset.asBool) {
        when(heldPhysical) {
            assert(io.physical.request.valid && io.physical.request.bits.asUInt === priorPhysical.asUInt,
                "held guest physical offer changed")
        }
        when(heldResponse) {
            assert(io.virtual.response.valid && Cat(io.virtual.response.bits.asUInt, io.guestFault.asUInt,
                io.cancelled, io.responseEpoch) === responseSnapshot, "guest response provenance changed under stall")
        }
        assert(!(io.physical.request.valid && io.virtual.response.valid), "guest request and completion overlap")
    }
}
