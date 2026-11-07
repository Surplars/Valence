package ooo

import chisel3._
import chisel3.util._
import soc.core.ooo._
import _root_.circt.stage.ChiselStage

class GuestInstructionAssemblerGsim extends Module {
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new GuestInstructionRequest))
        val response = Decoupled(new GuestInstructionResponse)
        val physical = new GuestScalarFetchPort(2)
        val memory = new SvPteReadPort
        val cancel = Input(Bool())
        val parcelStall = Input(Bool())
        val parcelOffer = Output(Bool())
        val parcelAccepted = Output(Bool())
        val parcelAddress = Output(UInt(64.W))
        val parcelEpoch = Output(UInt(8.W))
        val pmpTop = Input(UInt(54.W))
        val pmpPermission = Input(UInt(3.W))
        val physicalCheck = Output(Valid(new GuestPhysicalAccess))
        val pmaDenied = Input(Bool())
        val idle = Output(Bool())
    })
    val assembler = Module(new GuestInstructionAssembler)
    val fetch = Module(new GuestFetchTranslationAdapter(2))
    val translator = Module(new GuestTranslationService(8))
    assembler.io.request <> io.request
    io.response <> assembler.io.response
    fetch.io.virtual.request.valid := assembler.io.parcel.request.valid && !io.parcelStall
    fetch.io.virtual.request.bits := assembler.io.parcel.request.bits
    assembler.io.parcel.request.ready := fetch.io.virtual.request.ready && !io.parcelStall
    assembler.io.parcel.response <> fetch.io.virtual.response
    assembler.io.parcel.responseError := fetch.io.virtual.responseError
    assembler.io.parcel.responsePageFault := fetch.io.virtual.responsePageFault
    fetch.io.context := assembler.io.parcelContext
    fetch.io.cancel := assembler.io.parcelCancel
    assembler.io.parcelGuestFault := fetch.io.guestFault
    assembler.io.parcelCancelled := fetch.io.cancelled
    assembler.io.parcelResponseEpoch := fetch.io.responseEpoch
    assembler.io.parcelResponseAddress := fetch.io.responseAddress
    assembler.io.cancel := io.cancel
    io.parcelOffer := assembler.io.parcel.request.valid
    io.parcelAccepted := assembler.io.parcel.request.fire
    io.parcelAddress := assembler.io.parcel.request.bits
    io.parcelEpoch := assembler.io.parcelContext.epoch
    fetch.io.translation.request <> translator.io.request
    fetch.io.translation.response <> translator.io.response
    translator.io.cancel := fetch.io.translationCancel
    io.physical <> fetch.io.physical
    io.memory <> translator.io.memory
    io.physicalCheck := fetch.io.physicalCheck
    fetch.io.pmaDenied := io.pmaDenied
    io.idle := assembler.io.idle && fetch.io.idle && translator.io.idle
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := Cat(0.U(3.W), 1.U(2.W), io.pmpPermission)
    pmp.addr(0) := io.pmpTop
    PmpState.decodeRegions(pmp)
    translator.io.pmpState := pmp
}
object GuestInstructionAssemblerGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new GuestInstructionAssemblerGsim, Array("--target-dir", args(0)))
}
