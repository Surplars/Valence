package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class DualWriterRobCompletionDataWrite extends Bundle {
    val index = UInt(5.W)
    val data = UInt(64.W)
    val nextPc = UInt(64.W)
    val tval = UInt(64.W)
}

/** Raw component ports for the independent host array oracle.
  * select 0/1/2/3 chooses 4/8/16/32 rows. Only that slice accepts writes;
  * the host keeps addresses in range and samples these unregistered outputs
  * both before and after the edge. No RTL oracle is hidden here. Unwritten
  * storage is unspecified, including after reset.
  *
  * Explicit test-only RTL boundary mutants: 0 is normal; 1 swaps write data
  * and nextPc; 2 flips bit zero of both write indices (a bijection preserving
  * distinctness); 3 swaps the two returned data/nextPc lanes, not the head tval.
  * Mutant 3 is an output-boundary lane mutant, not an internal RAM-address or
  * last-writer-directory mutation. The production module has no mutation port.
  */
class DualWriterRobCompletionDataGsim extends Module {
    val io = IO(new Bundle {
        val select = Input(UInt(2.W))
        val mutation = Input(UInt(2.W))
        val head = Input(UInt(5.W))
        val write0 = Input(Valid(new DualWriterRobCompletionDataWrite))
        val write1 = Input(Valid(new DualWriterRobCompletionDataWrite))
        val data0 = Output(UInt(64.W))
        val data1 = Output(UInt(64.W))
        val nextPc0 = Output(UInt(64.W))
        val nextPc1 = Output(UInt(64.W))
        val headTval = Output(UInt(64.W))
    })

    val slices = Seq(4, 8, 16, 32).map(entries => Module(new DualWriterRobCompletionData(entries)))
    for ((slice, selected) <- slices.zipWithIndex) {
        val bits = log2Ceil(Seq(4, 8, 16, 32)(selected))
        slice.io.head := io.head(bits - 1, 0)
        for ((write, writer) <- Seq(io.write0, io.write1).zipWithIndex) {
            slice.io.write(writer).valid := write.valid && io.select === selected.U
            slice.io.write(writer).bits.index := write.bits.index(bits - 1, 0) ^
                Mux(io.mutation === 2.U, 1.U(bits.W), 0.U(bits.W))
            slice.io.write(writer).bits.data := Mux(io.mutation === 1.U, write.bits.nextPc, write.bits.data)
            slice.io.write(writer).bits.nextPc := Mux(io.mutation === 1.U, write.bits.data, write.bits.nextPc)
            slice.io.write(writer).bits.tval := write.bits.tval
        }
    }
    val data0 = Mux1H(slices.indices.map(i => (io.select === i.U) -> slices(i).io.data(0)))
    val data1 = Mux1H(slices.indices.map(i => (io.select === i.U) -> slices(i).io.data(1)))
    val nextPc0 = Mux1H(slices.indices.map(i => (io.select === i.U) -> slices(i).io.nextPc(0)))
    val nextPc1 = Mux1H(slices.indices.map(i => (io.select === i.U) -> slices(i).io.nextPc(1)))
    io.data0 := Mux(io.mutation === 3.U, data1, data0)
    io.data1 := Mux(io.mutation === 3.U, data0, data1)
    io.nextPc0 := Mux(io.mutation === 3.U, nextPc1, nextPc0)
    io.nextPc1 := Mux(io.mutation === 3.U, nextPc0, nextPc1)
    io.headTval := Mux1H(slices.indices.map(i => (io.select === i.U) -> slices(i).io.headTval))
}

object DualWriterRobCompletionDataGsimMain extends App {
    require(args.nonEmpty, "usage: DualWriterRobCompletionDataGsimMain OUTPUT_DIRECTORY")
    ChiselStage.emitCHIRRTLFile(new DualWriterRobCompletionDataGsim, Array("--target-dir", args.head))
}
