package ooo

import chisel3._
import soc.core.ooo._
import soc.ip.memory.NativeMemoryPort
import _root_.circt.stage.ChiselStage

class GuestDataTranslationGsim extends Module {
    val io = IO(new Bundle {
        val virtual = Flipped(new NativeMemoryPort(6))
        val physical = new NativeMemoryPort(6)
        val memory = new SvPteReadPort
        val context = Input(new GuestTranslationRequest)
        val cancel = Input(Bool())
        val pmpTop = Input(UInt(54.W))
        val pmpPermission = Input(UInt(3.W))
        val physicalCheck = Output(chisel3.util.Valid(new GuestPhysicalAccess))
        val pmaDenied = Input(Bool())
        val guestFault = Output(new GuestFaultMetadata)
        val cancelled = Output(Bool())
        val responseEpoch = Output(UInt(8.W))
        val idle = Output(Bool())
    })
    val adapter = Module(new GuestDataTranslationAdapter(6))
    val translator = Module(new GuestTranslationService(8))
    adapter.io.virtual <> io.virtual
    io.physical <> adapter.io.physical
    adapter.io.translation.request <> translator.io.request
    adapter.io.translation.response <> translator.io.response
    adapter.io.context := io.context
    adapter.io.cancel := io.cancel
    adapter.io.pmaDenied := io.pmaDenied
    io.physicalCheck := adapter.io.physicalCheck
    io.guestFault := adapter.io.guestFault
    io.cancelled := adapter.io.cancelled
    io.responseEpoch := adapter.io.responseEpoch
    translator.io.cancel := adapter.io.translationCancel
    io.memory <> translator.io.memory
    io.idle := adapter.io.idle && translator.io.idle
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := chisel3.util.Cat(0.U(3.W), 1.U(2.W), io.pmpPermission)
    pmp.addr(0) := io.pmpTop
    PmpState.decodeRegions(pmp)
    translator.io.pmpState := pmp
}
object GuestDataTranslationGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new GuestDataTranslationGsim, Array("--target-dir", args(0)))
}
