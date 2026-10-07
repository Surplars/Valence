package ooo

import _root_.circt.stage.ChiselStage
import chisel3._

/** Tool-capability probe, not a CDC bridge or CPU candidate.
  * Each counter advances only on its own Clock rising edge with enable high.
  * Explicit unrelated Clock inputs must not silently become one global tick.
  */
class IndependentClockProbeGsim extends RawModule {
    val clockA = IO(Input(Clock()))
    val clockB = IO(Input(Clock()))
    val resetA = IO(Input(AsyncReset()))
    val resetB = IO(Input(AsyncReset()))
    val enableA = IO(Input(Bool()))
    val enableB = IO(Input(Bool()))
    val countA = IO(Output(UInt(16.W)))
    val countB = IO(Output(UInt(16.W)))

    countA := withClockAndReset(clockA, resetA) {
        val counter = RegInit(0.U(16.W))
        when(enableA) { counter := counter + 1.U }
        counter
    }
    countB := withClockAndReset(clockB, resetB) {
        val counter = RegInit(0.U(16.W))
        when(enableB) { counter := counter + 1.U }
        counter
    }
}

object IndependentClockProbeGsimMain extends App {
    require(args.length == 1, "usage: IndependentClockProbeGsimMain output-directory")
    ChiselStage.emitCHIRRTLFile(new IndependentClockProbeGsim, Array("--target-dir", args.head))
}
