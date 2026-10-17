package soc.core.inorder

import chisel3._
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.{CdcResetRelease, CdcLevel}
import soc.ip.debug.BscanRamTransport

/** Clock/MIG remain outside this shell. Common active-low POR must also reset downstream AXI CDC/MIG.
  * Optional shared FPGA USER chain adds NO physical JTAG pins and NO architectural Debug Module.
  * The new-image BSCAN chain-collision/CDC timing audits remain mandatory before board delivery.
  */
class FiveStageFpgaShell(p: FiveStageSocConfig, jtagChain: Int = 0,
    jtagScanBits: Int = 64) extends RawModule {
    I1BscanRamTransport.validateScanBits(jtagScanBits)
    require(!p.managedPeripherals, "managed multi-clock peripherals require I1NetworkFpgaShell")
    require(if (p.withJtagLoader) Set(2, 3, 4).contains(jtagChain) else jtagChain == 0,
        "allocate a free FPGA USER2/3/4 explicitly; USER1 is reserved by the existing debug hub")
    val io = IO(new Bundle {
        val clockIn = Input(Clock()); val resetN = Input(Bool())
        val clockLocked = Input(Bool()); val ddrReady = Input(Bool())
        val uartRx = Input(Bool()); val uartTx = Output(Bool()); val externalIrq = Input(Bool())
        val resetHeld = Output(Bool()); val resetFault = Output(Bool())
        val ddrAxi = new Axi4MemoryPort(32, 4)
    })
    val release = Module(new CdcResetRelease)
    release.clockIn := io.clockIn; release.asyncReset := (!io.resetN).asAsyncReset
    val irq = Module(new CdcLevel)
    irq.clockIn := io.clockIn; irq.resetIn := release.resetOut; irq.levelIn := io.externalIrq
    val soc = withClockAndReset(io.clockIn, release.resetOut) { Module(new FiveStageSoc(p)) }
    soc.io.clockLocked := io.clockLocked; soc.io.ddrReady := io.ddrReady
    soc.io.uartRx := io.uartRx; soc.io.externalIrq := irq.levelOut
    io.uartTx := soc.io.uartTx; io.ddrAxi <> soc.io.ddrAxi
    io.resetHeld := release.resetOut.asBool || soc.io.resetHeld; io.resetFault := soc.io.resetFault
    if (p.withJtagLoader) {
        val transport = Module(new I1BscanRamTransport(jtagChain, p.core.fpgaTimingCuts, jtagScanBits))
        transport.io.debug_clk := io.clockIn; transport.io.debug_por_n := !release.resetOut.asBool
        soc.io.jtagLinkUp := transport.io.dmi_reset_n
        soc.io.jtagDmi.request.valid := transport.io.dmi_req_valid
        soc.io.jtagDmi.request.bits.op := transport.io.dmi_req_op
        soc.io.jtagDmi.request.bits.address := transport.io.dmi_req_address
        soc.io.jtagDmi.request.bits.data := transport.io.dmi_req_data
        transport.io.dmi_req_ready := soc.io.jtagDmi.request.ready
        transport.io.dmi_rsp_valid := soc.io.jtagDmi.response.valid
        transport.io.dmi_rsp_status := soc.io.jtagDmi.response.bits.status
        transport.io.dmi_rsp_data := soc.io.jtagDmi.response.bits.data
        soc.io.jtagDmi.response.ready := transport.io.dmi_rsp_ready
    } else {
        soc.io.jtagLinkUp := false.B; soc.io.jtagDmi.request.valid := false.B
        soc.io.jtagDmi.request.bits := 0.U.asTypeOf(soc.io.jtagDmi.request.bits)
        soc.io.jtagDmi.response.ready := false.B
    }
}
