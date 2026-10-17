package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._
import soc.ip.bus.TwoEntryRegisterQueue

class FiveStagePreparedQueueFixture(prepare: Boolean) extends Module {
    val io = IO(new QueueIO(UInt(64.W), 2))
    val current = Module(new I1PreparedRegisterQueue(UInt(64.W), prepare))
    val legacy = Module(new TwoEntryRegisterQueue(UInt(64.W)))
    current.io.enq <> io.enq; io.deq <> current.io.deq; io.count := current.io.count
    legacy.io.enq.valid := io.enq.valid; legacy.io.enq.bits := io.enq.bits
    legacy.io.deq.ready := io.deq.ready
    when(!reset.asBool) {
        assert(current.io.enq.ready === legacy.io.enq.ready, "native queue credit changed")
        assert(current.io.deq.valid === legacy.io.deq.valid && current.io.count === legacy.io.count,
            "native queue occupancy/latency changed")
        when(current.io.deq.valid) {
            assert(current.io.deq.bits === legacy.io.deq.bits, "prepared queue changed owned payload")
        }
    }
}

object FiveStagePreparedQueueMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStagePreparedQueueFixture(args.contains("--prepare")),
        Array("--target-dir", args.head))
}
