package soc.core.ooo

import chisel3._
import soc.ip.debug.{JtagDebugParams, JtagDebugReservation, BscanRamTransport}

/** Independent-project top with an explicit, separately reset debug reservation.
  * Existing BoardSocTop ports and defaults remain available as the reference.
  * Disabled debug adds only tied-off reservation pins, no TAP/CDC state or CPU
  * halt fan-out. Optional RAM download is a boot-owned custom DMI endpoint,
  * never architectural halt/debug; native multi-clock qualification is pending.
  */
class FpgaNextSocTop(config: FpgaNextConfig = FpgaNextConfig.Selected,
    debug: JtagDebugParams = JtagDebugParams(), bscanChain: Int = 0) extends Module {
    require(bscanChain >= 0 && bscanChain <= 4)
    require(bscanChain == 0 || !debug.enabled, "Select standalone TAP or FPGA USER transport, not both")
    private val ramDownload = debug.externalDmi || bscanChain != 0
    require(!debug.externalDmi || debug.addressBits == 7, "RAM loader uses seven DMI address bits")
    val board = Module(config.managedBoard(jtagRamDownload = ramDownload))
    val io = IO(chiselTypeOf(board.io))
    io <> board.io
    val jtag = IO(new Bundle {
        val tck = Input(Clock())
        val tms = Input(Bool())
        val tdi = Input(Bool())
        val trstN = Input(Bool())
        // Independent debug POR; do not connect a CPU warm reset here.
        val debugPorN = Input(Bool())
        val tdo = Output(Bool())
        val tdoOe = Output(Bool())
    })
    if (bscanChain != 0) {
        val transport = Module(new BscanRamTransport(bscanChain))
        transport.io.debug_clk := clock
        transport.io.debug_por_n := jtag.debugPorN
        val port = board.jtagDmi.get
        port.request.valid := transport.io.dmi_req_valid
        port.request.bits.op := transport.io.dmi_req_op
        port.request.bits.address := transport.io.dmi_req_address
        port.request.bits.data := transport.io.dmi_req_data
        transport.io.dmi_req_ready := port.request.ready
        transport.io.dmi_rsp_valid := port.response.valid
        transport.io.dmi_rsp_status := port.response.bits.status
        transport.io.dmi_rsp_data := port.response.bits.data
        port.response.ready := transport.io.dmi_rsp_ready
        board.jtagLinkUp.get := transport.io.dmi_reset_n
        jtag.tdo := false.B
        jtag.tdoOe := false.B
    } else {
        val transport = Module(new JtagDebugReservation(debug))
        transport.tck := jtag.tck
        transport.tms := jtag.tms
        transport.tdi := jtag.tdi
        transport.trstN := jtag.trstN
        transport.debugClock := (if (debug.externalDmi) clock else io.alwaysOnClock.get)
        transport.debugPorN := jtag.debugPorN
        if (debug.externalDmi) {
            // The loader and its coherent bus owner use the CPU/fabric clock/reset.
            // Transport reset only invalidates its session/interface, never the owner.
            board.jtagDmi.get <> transport.dmi
            board.jtagLinkUp.get := transport.dmiResetN
        } else {
            transport.dmi.request.ready := false.B
            transport.dmi.response.valid := false.B
            transport.dmi.response.bits := 0.U.asTypeOf(transport.dmi.response.bits)
        }
        jtag.tdo := transport.tdo
        jtag.tdoOe := transport.tdoOe
    }
}
