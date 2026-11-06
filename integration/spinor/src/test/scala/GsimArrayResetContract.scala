package spinor_integration

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

/** Tool contract only: dynamic-index reset arrays in two unrelated clocks. */
class GsimArrayResetContract extends RawModule {
    val clockA = IO(Input(Clock())); val clockB = IO(Input(Clock()))
    val asyncResetA = IO(Input(AsyncReset())); val resetB = IO(Input(Bool()))
    val io = IO(new Bundle {
        val indexA = Input(UInt(2.W)); val indexB = Input(UInt(2.W))
        val row = Input(UInt(1.W)); val column = Input(UInt(2.W))
        val writeA = Input(Bool()); val writeB = Input(Bool()); val writeMatrix = Input(Bool())
        val dataA = Input(UInt(8.W)); val dataB = Input(UInt(8.W)); val dataMatrix = Input(UInt(8.W))
        val a = Output(UInt(8.W)); val b = Output(UInt(8.W)); val matrix = Output(UInt(8.W))
    })
    val a = withClockAndReset(clockA, asyncResetA) {
        val values = RegInit(VecInit(Seq(0x11, 0x42, 0x83, 0xf0).map(_.U(8.W))))
        when(io.writeA) { values(io.indexA) := io.dataA }; values
    }
    val b = withClockAndReset(clockB, resetB) {
        val values = RegInit(VecInit(Seq(0xa0, 5, 0x7e).map(_.U(8.W))))
        when(io.writeB) { values(io.indexB) := io.dataB }; values
    }
    val matrix = withClockAndReset(clockA, asyncResetA) {
        val values = RegInit(VecInit(Seq.tabulate(2)(r =>
            VecInit(Seq.tabulate(3)(c => (0x20 + 3 * r + c).U(8.W))))))
        when(io.writeMatrix) { values(io.row)(io.column) := io.dataMatrix }; values
    }
    io.a := a(io.indexA); io.b := b(io.indexB); io.matrix := matrix(io.row)(io.column)
}
object GsimArrayResetContractMain extends App {
    ChiselStage.emitCHIRRTLFile(new GsimArrayResetContract, Array("--target-dir", args.head))
}
