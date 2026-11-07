package soc.core.ooo

import chisel3._
import chisel3.util._

class GuestInstructionRequest extends Bundle {
    val pc = UInt(64.W)
    val owner = UInt(64.W)
    val context = new GuestTranslationRequest
}

class GuestInstructionResponse extends Bundle {
    val instruction = UInt(32.W) // Raw 16-bit C encoding zero-extended, or the assembled 32-bit instruction.
    val compressed = Bool()
    val unsupportedLength = Bool() // Encoding requests >32 bits; caller must report illegal instruction.
    val bytes = UInt(3.W)
    val pc = UInt(64.W) // Architectural instruction start, including when its second parcel faults.
    val faultAddress = UInt(64.W) // Exact faulting parcel VA for tval, independent of pc/EPC.
    val owner = UInt(64.W)
    val epoch = UInt(8.W)
    val error = Bool()
    val pageFault = Bool()
    val guestFault = new GuestFaultMetadata
    val cancelled = Bool()
}

/** Little-endian RV C/32-bit instruction assembly above a two-byte guest fetch
  * adapter. Capacity one instruction, one parcel request outstanding, no overlap
  * or turnover bypass. One successful C instruction uses one parcel; a 32-bit
  * instruction uses two, independently translated at PC and PC+2, even across a
  * word or page boundary. This module does not decompress C or decode opcodes.
  *
  * A second-parcel fault preserves instruction PC/EPC and records PC+2 as tval.
  * Context, owner and epoch freeze at instruction acceptance. An offered parcel
  * cannot be revoked; cancellation is passed to its adapter after acceptance,
  * then drained into one instruction tombstone. Held instruction completions do
  * not change under late cancel; the caller must reject stale epochs/owners.
  * PMP/CSR/fence changes require draining the complete instruction owner, not
  * merely its first parcel. Encodings longer than 32 bits are explicitly marked
  * unsupported after the first parcel, with no speculative tail fetch.
  */
class GuestInstructionAssembler extends Module {
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new GuestInstructionRequest))
        val response = Decoupled(new GuestInstructionResponse)
        val parcel = new GuestScalarFetchPort(2)
        val parcelContext = Output(new GuestTranslationRequest)
        val parcelGuestFault = Input(new GuestFaultMetadata)
        val parcelCancelled = Input(Bool())
        val parcelResponseEpoch = Input(UInt(8.W))
        val parcelResponseAddress = Input(UInt(64.W))
        val cancel = Input(Bool())
        val parcelCancel = Output(Bool())
        val idle = Output(Bool())
    })
    val Seq(idle, offerFirst, waitFirst, offerSecond, waitSecond, reply) = Enum(6)
    val state = RegInit(idle)
    val saved = Reg(new GuestInstructionRequest)
    val result = RegInit(0.U.asTypeOf(new GuestInstructionResponse))
    val first = Reg(UInt(16.W))
    val killed = RegInit(false.B)
    val killNow = killed || io.cancel
    val second = state === offerSecond || state === waitSecond
    val parcelAddress = Mux(second, saved.pc + 2.U, saved.pc)
    val waiting = state === waitFirst || state === waitSecond
    io.idle := state === idle
    io.request.ready := state === idle && !io.cancel
    io.response.valid := state === reply
    io.response.bits := result
    io.parcel.request.valid := state === offerFirst || state === offerSecond
    io.parcel.request.bits := parcelAddress
    io.parcel.response.ready := waiting
    io.parcelContext := saved.context
    io.parcelContext.virtualAddress := parcelAddress
    io.parcelContext.access := PmpAccess.execute
    io.parcelContext.size := 1.U
    io.parcelContext.forceExecute := false.B
    // An asserted adapter cancel would suppress its idle request READY. Delay
    // propagation until the already presented parcel offer has been accepted.
    io.parcelCancel := waiting && killNow

    def cancelledReply(): Unit = {
        result.instruction := 0.U
        result.error := false.B
        result.pageFault := false.B
        result.guestFault := 0.U.asTypeOf(new GuestFaultMetadata)
        result.cancelled := true.B
        result.unsupportedLength := false.B
        result.faultAddress := 0.U
        state := reply
    }
    when(io.request.fire) {
        saved := io.request.bits
        result := 0.U.asTypeOf(new GuestInstructionResponse)
        result.pc := io.request.bits.pc
        result.faultAddress := io.request.bits.pc
        result.owner := io.request.bits.owner
        result.epoch := io.request.bits.context.epoch
        result.bytes := 2.U
        killed := false.B
        state := offerFirst
        assert(!io.request.bits.pc(0), "instruction assembler requires a halfword-aligned PC")
    }
    when(io.parcel.request.fire) { state := Mux(second, waitSecond, waitFirst) }
    when(io.parcel.response.fire) {
        assert(io.parcelResponseEpoch === saved.context.epoch && io.parcelResponseAddress === parcelAddress,
            "guest instruction parcel response lost its accepted owner/address/epoch")
        when(io.parcelCancelled || killNow) { cancelledReply() }
            .elsewhen(io.parcel.responseError || io.parcel.responsePageFault || io.parcelGuestFault.guestPageFault) {
                result.error := true.B
                result.pageFault := io.parcel.responsePageFault
                result.guestFault := io.parcelGuestFault
                result.faultAddress := parcelAddress
                state := reply
            }.elsewhen(second) {
                result.instruction := Cat(io.parcel.response.bits, first)
                result.guestFault := io.parcelGuestFault
                state := reply
            }.otherwise {
                first := io.parcel.response.bits
                result.instruction := io.parcel.response.bits
                result.guestFault := io.parcelGuestFault
                when(io.parcel.response.bits(1, 0) =/= 3.U) {
                    result.compressed := true.B
                    state := reply
                }.elsewhen(io.parcel.response.bits(4, 2) === 7.U) {
                    result.unsupportedLength := true.B
                    state := reply
                }.otherwise {
                    result.bytes := 4.U
                    state := offerSecond
                }
            }
    }
    when(state =/= idle && state =/= reply && io.cancel) { killed := true.B }
    when(io.response.fire) { state := idle }

    val heldParcel = RegNext(io.parcel.request.valid && !io.parcel.request.ready, false.B)
    val previousParcel = RegEnable(Cat(io.parcel.request.bits, io.parcelContext.asUInt),
        io.parcel.request.valid && !io.parcel.request.ready)
    val heldResponse = RegNext(io.response.valid && !io.response.ready, false.B)
    val previousResponse = RegEnable(io.response.bits, io.response.valid && !io.response.ready)
    when(!reset.asBool) {
        when(heldParcel) {
            assert(io.parcel.request.valid && Cat(io.parcel.request.bits, io.parcelContext.asUInt) === previousParcel,
                "held instruction parcel request/context changed")
        }
        when(heldResponse) {
            assert(io.response.valid && io.response.bits.asUInt === previousResponse.asUInt,
                "held assembled instruction/provenance changed")
        }
        assert(!(io.response.valid && io.parcel.request.valid), "instruction completion retained a parcel offer")
    }
}
