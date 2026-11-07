package soc.core.ooo

import chisel3._
import chisel3.util._

/** One naturally aligned instruction parcel. The physical endpoint returns the
  * exact requested parcel, not a shifted native-memory beat. Packet assembly and
  * the first faulting parcel's architectural instruction PC belong to the caller.
  */
class GuestScalarFetchPort(val parcelBytes: Int = 4) extends Bundle {
    require(Set(2, 4).contains(parcelBytes))
    val request = Decoupled(UInt(64.W))
    val response = Flipped(Decoupled(UInt((parcelBytes * 8).W)))
    val responseError = Input(Bool())
    val responsePageFault = Input(Bool())
}

/** Single-owner conservative guest instruction translator. Capacity=1, no
  * turnover or identity bypass. Every fetch, including VS Bare, traverses the
  * captured translation context. The caller assembles packets/instructions from
  * 2-byte or 4-byte aligned parcels and retains the original faulting parcel VA.
  *
  * All fetch owners are cancellable. An offered translation/physical request is
  * held until acceptance, then drained; a cancelled owner returns one tombstone.
  * Completion sidebands stay immutable while valid and stalled. The caller must
  * honor cancelled/epoch, drain on fences, and enforce executable, side-effect-
  * free physical PMA using physicalCheck/pmaDenied before the physical offer.
  */
class GuestFetchTranslationAdapter(parcelBytes: Int = 4) extends Module {
    require(Set(2, 4).contains(parcelBytes))
    val io = IO(new Bundle {
        val virtual = Flipped(new GuestScalarFetchPort(parcelBytes))
        val physical = new GuestScalarFetchPort(parcelBytes)
        val translation = new GuestTranslationPort
        val context = Input(new GuestTranslationRequest)
        val cancel = Input(Bool())
        val translationCancel = Output(Bool())
        val physicalCheck = Output(Valid(new GuestPhysicalAccess))
        val pmaDenied = Input(Bool())
        val guestFault = Output(new GuestFaultMetadata)
        val cancelled = Output(Bool())
        val responseEpoch = Output(UInt(8.W))
        val responseAddress = Output(UInt(64.W))
        val idle = Output(Bool())
    })
    val Seq(idle, offerTranslation, waitTranslation, checkPhysical, offerPhysical, waitPhysical, reply) = Enum(7)
    val state = RegInit(idle)
    val context = Reg(new GuestTranslationRequest)
    val physicalAddress = Reg(UInt(64.W))
    val data = RegInit(0.U((parcelBytes * 8).W))
    val error = RegInit(false.B)
    val pageFault = RegInit(false.B)
    val fault = RegInit(0.U.asTypeOf(new GuestFaultMetadata))
    val killed = RegInit(false.B)
    val wasCancelled = RegInit(false.B)
    val killNow = killed || io.cancel

    io.idle := state === idle
    io.virtual.request.ready := state === idle && !io.cancel
    io.virtual.response.valid := state === reply
    io.virtual.response.bits := data
    io.virtual.responseError := error
    io.virtual.responsePageFault := pageFault
    io.guestFault := fault
    io.cancelled := wasCancelled
    io.responseEpoch := context.epoch
    io.responseAddress := context.virtualAddress
    io.translation.request.valid := state === offerTranslation
    io.translation.request.bits := context
    io.translation.response.ready := state === waitTranslation
    io.translationCancel := state === waitTranslation && killNow
    io.physical.request.valid := state === offerPhysical
    io.physical.request.bits := physicalAddress
    io.physical.response.ready := state === waitPhysical
    io.physicalCheck.valid := state === checkPhysical
    io.physicalCheck.bits.address := physicalAddress
    io.physicalCheck.bits.size := log2Ceil(parcelBytes).U
    io.physicalCheck.bits.access := PmpAccess.execute
    io.physicalCheck.bits.forceExecute := false.B

    def cancelledReply(): Unit = {
        data := 0.U
        error := false.B
        pageFault := false.B
        fault := 0.U.asTypeOf(new GuestFaultMetadata)
        wasCancelled := true.B
        state := reply
    }
    when(io.virtual.request.fire) {
        context := io.context
        context.virtualAddress := io.virtual.request.bits
        context.access := PmpAccess.execute
        context.size := log2Ceil(parcelBytes).U
        context.forceExecute := false.B
        data := 0.U
        error := false.B
        pageFault := false.B
        fault := 0.U.asTypeOf(new GuestFaultMetadata)
        fault.guestAddress := io.context.virtualized
        killed := false.B
        wasCancelled := false.B
        state := offerTranslation
        assert(io.virtual.request.bits(log2Ceil(parcelBytes) - 1, 0) === 0.U,
            "guest fetch parcel must be naturally aligned; split crossing instructions upstream")
    }
    when(io.translation.request.fire) { state := waitTranslation }
    when(io.translation.response.fire) {
        val translated = io.translation.response.bits
        assert(translated.epoch === context.epoch && translated.virtualAddress === context.virtualAddress,
            "guest fetch translation lost its captured parcel owner")
        when(translated.cancelled || killNow) { cancelledReply() }
            .otherwise {
                fault.guestAddress := context.virtualized
                fault.guestPageFault := translated.guestPageFault
                fault.guestPhysicalAddress := Mux(translated.guestPageFault, translated.guestPhysicalAddress, 0.U)
                fault.implicitPte := translated.guestPageFault && translated.implicitPte
                when(translated.pageFault || translated.guestPageFault || translated.accessFault) {
                    error := true.B
                    pageFault := translated.pageFault
                    state := reply
                }.otherwise {
                    physicalAddress := translated.physicalAddress
                    state := checkPhysical
                }
            }
    }
    when(state === checkPhysical) {
        when(killNow) { cancelledReply() }
            .elsewhen(io.pmaDenied) { error := true.B; state := reply }
            .otherwise { state := offerPhysical }
    }
    when(io.physical.request.fire) { state := waitPhysical }
    when(io.physical.response.fire) {
        data := io.physical.response.bits
        error := io.physical.responseError
        assert(!io.physical.responsePageFault, "physical instruction endpoint returned a virtual page fault")
        state := reply
        when(killNow) { cancelledReply() }
    }
    when(state =/= idle && state =/= reply && io.cancel) { killed := true.B }
    when(io.virtual.response.fire) { state := idle }

    val heldPhysical = RegNext(io.physical.request.valid && !io.physical.request.ready, false.B)
    val previousAddress = RegEnable(io.physical.request.bits, io.physical.request.valid && !io.physical.request.ready)
    val heldResponse = RegNext(io.virtual.response.valid && !io.virtual.response.ready, false.B)
    val responseBits = Cat(io.virtual.response.bits, io.virtual.responseError, io.virtual.responsePageFault,
        io.guestFault.asUInt, io.cancelled, io.responseEpoch, io.responseAddress)
    val previousResponse = RegEnable(responseBits, io.virtual.response.valid && !io.virtual.response.ready)
    when(!reset.asBool) {
        when(heldPhysical) {
            assert(io.physical.request.valid && io.physical.request.bits === previousAddress,
                "held physical instruction fetch was changed or withdrawn")
        }
        when(heldResponse) {
            assert(io.virtual.response.valid && responseBits === previousResponse,
                "held guest fetch response lost its fault or epoch provenance")
        }
        assert(!(io.physical.request.valid && io.virtual.response.valid), "fetch request and completion overlap")
    }
}
