package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo.{GuestInterruptCsrWrite, HypervisorGuestInterrupts}
import soc.ip.bus._
import soc.ip.interrupt._

/** Real APLIC pair -> IMSIC -> H interrupt-state component chain.
  * This fixture does not instantiate a CPU, authorize CSR instructions, or enter traps.
  * CSR file selection is explicit at the test port, as at the production IMSIC boundary.
  */
class AiaGuestRoutingGsim extends Module {
    val io = IO(new Bundle {
        val sources = Input(UInt(8.W))
        val machine = Flipped(new RegisterPort)
        val supervisor = Flipped(new RegisterPort)
        val csrRequest = Flipped(Decoupled(new ImsicCsrRequest))
        val csrResponse = Decoupled(new RegisterResponse)
        val allowMsi = Input(Bool())
        val msiValid = Output(Bool()); val msiFire = Output(Bool())
        val msiAddress = Output(UInt(64.W)); val msiData = Output(UInt(64.W))
        val commit = Input(Bool())
        val write = Flipped(Valid(new GuestInterruptCsrWrite))
        val setVgein = Flipped(Valid(UInt(6.W)))
        val hie = Input(UInt(64.W)); val hideleg = Input(UInt(64.W))
        val privilege = Input(UInt(2.W)); val virtualized = Input(Bool())
        val hsGlobalEnable = Input(Bool()); val vsGlobalEnable = Input(Bool())
        val hgeip = Output(UInt(64.W)); val hgeie = Output(UInt(64.W))
        val hip = Output(UInt(64.W)); val vsip = Output(UInt(64.W))
        val vgein = Output(UInt(6.W))
        val hsPending = Output(Bool()); val hsCause = Output(UInt(4.W))
        val vsPending = Output(Bool()); val vsCause = Output(UInt(4.W))
    })
    val aia = Module(new AiaGuestGsim(2))
    val guest = Module(new HypervisorGuestInterrupts(2))
    aia.io.sources := io.sources
    aia.io.machine <> io.machine; aia.io.supervisor <> io.supervisor
    aia.io.csrRequest <> io.csrRequest; aia.io.csrResponse <> io.csrResponse
    aia.io.injection.request.valid := false.B
    aia.io.injection.request.bits := 0.U.asTypeOf(aia.io.injection.request.bits)
    aia.io.injection.response.ready := true.B
    aia.io.allowMsi := io.allowMsi
    aia.io.allowMsiResponse := true.B
    io.msiValid := aia.io.msiValid; io.msiFire := aia.io.msiFire
    io.msiAddress := aia.io.msiAddress; io.msiData := aia.io.msiData
    guest.io.guestExternal := aia.io.interrupts(3, 2)
    guest.io.commit := io.commit; guest.io.write := io.write; guest.io.setVgein := io.setVgein
    guest.io.platformVirtualExternal := false.B; guest.io.virtualTimer := false.B
    guest.io.readAddress := 0.U
    guest.io.hie := io.hie; guest.io.hideleg := io.hideleg
    guest.io.privilege := io.privilege; guest.io.virtualized := io.virtualized
    guest.io.hsGlobalEnable := io.hsGlobalEnable; guest.io.vsGlobalEnable := io.vsGlobalEnable
    io.hgeip := guest.io.hgeip; io.hgeie := guest.io.hgeie
    io.hip := guest.io.hip; io.vsip := guest.io.vsip; io.vgein := guest.io.vgein
    io.hsPending := guest.io.hsPending; io.hsCause := guest.io.hsCause
    io.vsPending := guest.io.vsPending; io.vsCause := guest.io.vsCause
    assert(!aia.io.msiError, "APLIC-to-guest MSI transaction failed")
}
object AiaGuestRoutingGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new AiaGuestRoutingGsim, Array("--target-dir", args(0)))
}
