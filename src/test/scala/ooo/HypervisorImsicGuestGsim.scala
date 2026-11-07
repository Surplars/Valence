package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo.{GuestInterruptCsrWrite, HypervisorGuestInterrupts}
import soc.ip.bus.{RegisterPort, RegisterResponse}
import soc.ip.interrupt.{Imsic, ImsicCsrRequest, ImsicParams}

/** Test-only physical IMSIC -> H interrupt composition. No processor or CSR privilege decoder. */
class HypervisorImsicGuestGsim extends Module {
    val io = IO(new Bundle {
        val mmio = Flipped(new RegisterPort)
        val csr = Flipped(Decoupled(new ImsicCsrRequest))
        val response = Decoupled(new RegisterResponse)
        val write = Flipped(Valid(new GuestInterruptCsrWrite))
        val setVgein = Flipped(Valid(UInt(6.W)))
        val hie = Input(UInt(64.W))
        val hideleg = Input(UInt(64.W))
        val virtualized = Input(Bool())
        val hsGlobalEnable = Input(Bool())
        val vsGlobalEnable = Input(Bool())
        val hgeip = Output(UInt(64.W))
        val hip = Output(UInt(64.W))
        val hsPending = Output(Bool())
        val hsCause = Output(UInt(4.W))
        val vsPending = Output(Bool())
        val vsCause = Output(UInt(4.W))
    })
    val imsic = Module(new Imsic(ImsicParams(identities = 127, guestFiles = 3)))
    val guest = Module(new HypervisorGuestInterrupts(3))
    imsic.io.mmio <> io.mmio
    imsic.io.csrRequest <> io.csr
    io.response <> imsic.io.csrResponse
    guest.io.guestExternal := imsic.io.interrupts(4, 2)
    guest.io.commit := true.B
    guest.io.write := io.write
    guest.io.setVgein := io.setVgein
    guest.io.readAddress := 0.U
    guest.io.platformVirtualExternal := false.B
    guest.io.virtualTimer := false.B
    guest.io.hie := io.hie
    guest.io.hideleg := io.hideleg
    guest.io.privilege := 1.U
    guest.io.virtualized := io.virtualized
    guest.io.hsGlobalEnable := io.hsGlobalEnable
    guest.io.vsGlobalEnable := io.vsGlobalEnable
    io.hgeip := guest.io.hgeip
    io.hip := guest.io.hip
    io.hsPending := guest.io.hsPending
    io.hsCause := guest.io.hsCause
    io.vsPending := guest.io.vsPending
    io.vsCause := guest.io.vsCause
}
object HypervisorImsicGuestGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new HypervisorImsicGuestGsim, Array("--target-dir", args(0)))
}
