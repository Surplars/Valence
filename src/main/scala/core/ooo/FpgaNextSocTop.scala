package soc.core.ooo

import chisel3._
import soc.ip.debug.{JtagDebugParams, JtagDebugReservation}

/** Independent-project top with an explicit, separately reset debug reservation.
  * Existing BoardSocTop ports and defaults remain available as the reference.
  * Disabled debug adds only tied-off reservation pins, no TAP/CDC state or CPU
  * halt fan-out. Enabled transport is an opt-in, unavailable-DM experiment until
  * its independent multi-clock qualification gate has passed.
  */
class FpgaNextSocTop(config: FpgaNextConfig = FpgaNextConfig.Selected,
    debug: JtagDebugParams = JtagDebugParams()) extends Module {
    require(!debug.externalDmi, "the integrated reservation has no architectural debug module")
    val board = Module(config.managedBoard)
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
    val transport = Module(new JtagDebugReservation(debug))
    transport.tck := jtag.tck
    transport.tms := jtag.tms
    transport.tdi := jtag.tdi
    transport.trstN := jtag.trstN
    transport.debugClock := io.alwaysOnClock.get
    transport.debugPorN := jtag.debugPorN
    transport.dmi.request.ready := false.B
    transport.dmi.response.valid := false.B
    transport.dmi.response.bits := 0.U.asTypeOf(transport.dmi.response.bits)
    jtag.tdo := transport.tdo
    jtag.tdoOe := transport.tdoOe
}
