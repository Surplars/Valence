package soc.core.ooo

import chisel3._
import chisel3.util._

/** Committed CSR updates only. Access/privilege checks and CSR RMW are the caller's responsibility. */
class GuestInterruptCsrWrite extends Bundle {
    val address = UInt(12.W)
    val data = UInt(64.W)
}

/** RV64 H 1.0 guest-interrupt state and local routing, independent of a pipeline.
  *
  * guestExternal bit 0 denotes IMSIC guest file 1, not the machine or supervisor file.
  * The corresponding hgeip bit is 1. hgeie gates only SGEIP, never the VGEIN-selected VSEIP.
  * A caller supplies the effective hie and hideleg views and combines the two local candidates
  * with ordinary M/HS interrupts. This module does not implement trap entry, the complete H CSR
  * bank, AIA programmable priorities, or two-stage translation, and does not enable misa.H.
  */
class HypervisorGuestInterrupts(guestFiles: Int = 0) extends Module {
    require(guestFiles >= 0 && guestFiles <= 63, "RV64 GEILEN must be between 0 and 63")
    val io = IO(new Bundle {
        val guestExternal = Input(UInt(math.max(1, guestFiles).W))
        val platformVirtualExternal = Input(Bool())
        val virtualTimer = Input(Bool()) // Qualified vstimecmp signal, or false without guest Sstc.
        val commit = Input(Bool())
        val write = Flipped(Valid(new GuestInterruptCsrWrite))
        val setVgein = Flipped(Valid(UInt(6.W)))
        val readAddress = Input(UInt(12.W))
        val readKnown = Output(Bool())
        val readData = Output(UInt(64.W))
        val hgeip = Output(UInt(64.W))
        val hgeie = Output(UInt(64.W))
        val hvip = Output(UInt(64.W))
        val hip = Output(UInt(64.W))
        val vgein = Output(UInt(6.W))
        val vsip = Output(UInt(64.W))
        val hie = Input(UInt(64.W))
        val hideleg = Input(UInt(64.W))
        val privilege = Input(UInt(2.W))
        val virtualized = Input(Bool())
        val hsGlobalEnable = Input(Bool())
        val vsGlobalEnable = Input(Bool())
        val hsPending = Output(Bool())
        val hsCause = Output(UInt(4.W))
        val vsPending = Output(Bool())
        val vsCause = Output(UInt(4.W))
    })
    private val guestMask = ((BigInt(1) << (guestFiles + 1)) - 2).U(64.W)
    private val virtualMask = "h444".U(64.W)
    private val implemented = (if (guestFiles == 0) BigInt(0x444) else BigInt(0x1444)).U(64.W)
    private val enabled = RegInit(0.U(64.W))
    private val injected = RegInit(0.U(64.W))
    private val selected = RegInit(0.U(6.W))
    private val external = if (guestFiles == 0) 0.U(64.W)
        else Cat(io.guestExternal, 0.U(1.W)).pad(64)
    when(io.commit && io.setVgein.valid) {
        // VGEIN is WLRL. This implementation maps unsupported encodings to zero.
        selected := Mux(io.setVgein.bits <= guestFiles.U, io.setVgein.bits, 0.U)
    }
    when(io.commit && io.write.valid) {
        switch(io.write.bits.address) {
            is("h607".U) { enabled := io.write.bits.data & guestMask }
            is("h645".U) { injected := io.write.bits.data & virtualMask }
            is("h644".U) {
                // hip.VSSIP aliases hvip.VSSIP. VSEIP/VSTIP/SGEIP are read-only.
                injected := (injected & "hfffffffffffffffb".U) | (io.write.bits.data & 4.U)
            }
        }
    }
    val guestSummary = (external & enabled).orR
    val virtualExternal = injected(10) || external(selected) || io.platformVirtualExternal
    val virtualTimer = injected(6) || io.virtualTimer
    val pending = (guestSummary.asUInt << 12) | (virtualExternal.asUInt << 10) |
        (virtualTimer.asUInt << 6) | (injected(2).asUInt << 2)
    io.hgeip := external
    io.hgeie := enabled
    io.hvip := injected
    io.hip := pending
    io.vgein := selected
    val delegation = io.hideleg & virtualMask // SGEI cannot be delegated to VS.
    io.vsip := (pending & delegation) >> 1
    val readValues = Seq("h607".U -> enabled, "he12".U -> external,
        "h644".U -> pending.pad(64), "h645".U -> injected)
    io.readKnown := readValues.map { case (address, _) => io.readAddress === address }.reduce(_ || _)
    io.readData := Mux1H(readValues.map { case (address, data) => (io.readAddress === address) -> data })
    val hs = pending & io.hie & implemented & ~delegation
    val vs = pending & io.hie & delegation
    val hsAllowed = io.privilege === 0.U ||
        (io.privilege === 1.U && (io.virtualized || io.hsGlobalEnable))
    val vsAllowed = io.virtualized && (io.privilege === 0.U ||
        (io.privilege === 1.U && io.vsGlobalEnable))
    io.hsPending := hs.orR && hsAllowed
    io.vsPending := vs.orR && vsAllowed
    // H 1.0 fixed local order. Ordinary HS SEI/SSI/STI precede this group.
    io.hsCause := Mux(hs(12), 12.U, Mux(hs(10), 10.U, Mux(hs(2), 2.U, 6.U)))
    io.vsCause := Mux(vs(10), 9.U, Mux(vs(2), 1.U, 5.U))
}
