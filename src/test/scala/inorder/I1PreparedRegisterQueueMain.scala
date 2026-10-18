package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder.I1PreparedRegisterQueue

/** Real prepared queue paired with the old owner-enabled implementation.
  * The C++ oracle independently tracks two slots, accepted bytes and edges.
  */
class I1PreparedRegisterQueueFixture extends Module {
    val io = IO(new Bundle {
        val valid = Input(Bool()); val ready = Output(Bool())
        // Keep top-level GSIM ports scalar; the pinned emitter does not expose
        // wide aggregate setters. The actual tested payload remains 192 bits.
        val data_0 = Input(UInt(64.W)); val data_1 = Input(UInt(64.W)); val data_2 = Input(UInt(64.W))
        val consume = Input(Bool()); val available = Output(Bool())
        val result_0 = Output(UInt(64.W)); val result_1 = Output(UInt(64.W)); val result_2 = Output(UInt(64.W))
        val count = Output(UInt(2.W))
    })
    val dut = Module(new I1PreparedRegisterQueue(Vec(3, UInt(64.W)), preparePayload = true))
    val reference = Module(new I1PreparedRegisterQueue(Vec(3, UInt(64.W)), preparePayload = false))
    for (q <- Seq(dut, reference)) {
        q.io.enq.valid := io.valid
        q.io.enq.bits := VecInit(Seq(io.data_0, io.data_1, io.data_2))
        q.io.deq.ready := io.consume
    }
    io.ready := dut.io.enq.ready; io.available := dut.io.deq.valid
    io.result_0 := dut.io.deq.bits(0); io.result_1 := dut.io.deq.bits(1); io.result_2 := dut.io.deq.bits(2)
    io.count := dut.io.count
    when(!reset.asBool) {
        assert(dut.io.enq.ready === reference.io.enq.ready && dut.io.deq.valid === reference.io.deq.valid &&
            dut.io.count === reference.io.count, "prepared queue changed ready/valid/count/edge")
        when(dut.io.deq.valid) {
            assert(dut.io.deq.bits.asUInt === reference.io.deq.bits.asUInt,
                "prepared queue overwrote an owned payload")
        }
    }
}
object I1PreparedRegisterQueueMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1PreparedRegisterQueueFixture, Array("--target-dir", args.head))
}
