package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder.{I1DataResponse, I1FlowResponseQueue}

class I1FlowResponseQueueFixture(entries: Int) extends Module {
    val io = IO(new QueueIO(new I1DataResponse, entries))
    val queue = Module(new I1FlowResponseQueue(new I1DataResponse, entries))
    queue.io.enq <> io.enq
    io.deq <> queue.io.deq
    io.count := queue.io.count
    val reference = Module(new Queue(new I1DataResponse, entries, pipe = false, flow = true))
    reference.io.enq.valid := io.enq.valid
    reference.io.enq.bits := io.enq.bits
    reference.io.deq.ready := io.deq.ready
    when(!reset.asBool) {
        assert(io.enq.ready === reference.io.enq.ready && io.deq.valid === reference.io.deq.valid &&
            io.count === reference.io.count, "response queue changed standard flow/credit semantics")
        when(io.deq.valid) {
            assert(io.deq.bits.asUInt === reference.io.deq.bits.asUInt,
                "response queue changed standard ordered payload")
        }
    }
}

object I1FlowResponseQueueMain extends App {
    val entries = args.find(_.startsWith("--entries=")).map(_.stripPrefix("--entries=").toInt).getOrElse(2)
    ChiselStage.emitCHIRRTLFile(new I1FlowResponseQueueFixture(entries),
        Array("--target-dir", args.head))
}
