package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder.I1PreparedMetadataQueue

/** Actual candidate and standard non-pipe/non-flow reference, every cycle.
  * The C++ driver separately checks accepted byte order and capacity.
  */
class I1PreparedMetadataFixture(entries: Int) extends Module {
    val io = IO(new QueueIO(UInt(4.W), entries))
    val dut = Module(new I1PreparedMetadataQueue(4, entries))
    val reference = Module(new Queue(UInt(4.W), entries, pipe = false, flow = false))
    io <> dut.io
    reference.io.enq.valid := io.enq.valid
    reference.io.enq.bits := io.enq.bits
    reference.io.deq.ready := io.deq.ready
    when(!reset.asBool) {
        assert(dut.io.enq.ready === reference.io.enq.ready &&
            dut.io.deq.valid === reference.io.deq.valid && dut.io.count === reference.io.count,
            "prepared metadata changed occupancy/handshake/latency")
        when(dut.io.deq.valid) {
            assert(dut.io.deq.bits === reference.io.deq.bits,
                "prepared metadata overwrote a live queue owner")
        }
    }
}
object I1PreparedMetadataMain extends App {
    val entries = args.find(_.startsWith("--entries=")).map(_.stripPrefix("--entries=").toInt).getOrElse(4)
    ChiselStage.emitCHIRRTLFile(new I1PreparedMetadataFixture(entries), Array("--target-dir", args.head))
}
