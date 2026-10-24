package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Direct storage-only fixture. The host supplies already-qualified capture and
  * consume prefixes; there is no fixture bypass, payload transformation, or
  * credit borrowed from consumption. Invalid payload/lookahead bits are not
  * part of the interface contract.
  */
class CircularFetchStorageGsim extends Module {
    val io = IO(new Bundle {
        val capture0 = Input(Valid(new RawFetchInstruction))
        val capture1 = Input(Valid(new RawFetchInstruction))
        val consume0 = Input(Bool())
        val consume1 = Input(Bool())
        val cancel = Input(Bool())
        val lane0 = Output(Valid(new RawFetchInstruction))
        val lane1 = Output(Valid(new RawFetchInstruction))
        val lookaheadPc0 = Output(UInt(64.W))
        val lookaheadPc1 = Output(UInt(64.W))
        val lookaheadPc2 = Output(UInt(64.W))
        val occupancy = Output(UInt(3.W))
    })
    val storage = Module(new CircularFetchInstructionStorage)
    storage.io.capture(0) := io.capture0
    storage.io.capture(1) := io.capture1
    storage.io.consume(0) := io.consume0
    storage.io.consume(1) := io.consume1
    storage.io.cancel := io.cancel
    io.lane0 := storage.io.instructions(0)
    io.lane1 := storage.io.instructions(1)
    io.lookaheadPc0 := storage.io.lookaheadPc(0)
    io.lookaheadPc1 := storage.io.lookaheadPc(1)
    io.lookaheadPc2 := storage.io.lookaheadPc(2)
    io.occupancy := storage.io.occupancy
}

object CircularFetchStorageGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CircularFetchStorageGsim, Array("--target-dir", args.head))
}
