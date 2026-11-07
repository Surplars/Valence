package ooo

import chisel3._
import soc.core.ooo._
import _root_.circt.stage.ChiselStage

/** Preserve the real PMP checker while exposing a compact physical allow/deny region. */
class GuestTranslationGsim extends Module {
    val io = IO(new Bundle {
        val request = Flipped(chisel3.util.Decoupled(new GuestTranslationRequest))
        val response = chisel3.util.Decoupled(new GuestTranslationResponse)
        val memory = new SvPteReadPort
        val cancel = Input(Bool())
        val idle = Output(Bool())
        val pmpTop = Input(UInt(54.W))
        val pmpPermission = Input(UInt(3.W))
    })
    val dut = Module(new GuestTranslationService(8))
    dut.io.request <> io.request
    io.response <> dut.io.response
    io.memory <> dut.io.memory
    dut.io.cancel := io.cancel
    io.idle := dut.io.idle
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := chisel3.util.Cat(0.U(3.W), 1.U(2.W), io.pmpPermission)
    pmp.addr(0) := io.pmpTop
    PmpState.decodeRegions(pmp)
    dut.io.pmpState := pmp
}
object GuestTranslationGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new GuestTranslationGsim, Array("--target-dir", args(0)))
}
