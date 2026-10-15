package soc.core.ooo

import chisel3._
import chisel3.util._

/** Request and CPU proof cross the same existing FIFO boundary atomically.
  * Capacity/latency/ready are exactly Queue(pipe=false, flow=false): no bypass,
  * no full dequeue-to-enqueue ready path, and one transfer per cycle after fill.
  * Flush/quiesce do not erase an already accepted LSU response owner. The
  * original request acceptance and downstream authorization gates remain outside.
  */
class RegisteredRequestQueue(p: OooParams) extends Module {
    val io = IO(new QueueIO(new DataRequest(p.dataReturnHandleBits), p.memoryEntries))
    val proofIn = p.postedProofConfig.map(c => IO(Input(Valid(new PostedStoreProof(c)))))
    val proofOut = p.postedProofConfig.map(c => IO(Output(Valid(new PostedStoreProof(c)))))

    p.postedProofConfig match {
        case Some(c) =>
            val entries = Module(new Queue(new Bundle {
                val request = new DataRequest(p.dataReturnHandleBits)
                val proof = Valid(new PostedStoreProof(c))
            }, p.memoryEntries, pipe = false, flow = false, useSyncReadMem = false))
            entries.io.enq.valid := io.enq.valid
            entries.io.enq.bits.request := io.enq.bits
            entries.io.enq.bits.proof := proofIn.get
            io.enq.ready := entries.io.enq.ready
            io.deq.valid := entries.io.deq.valid
            io.deq.bits := entries.io.deq.bits.request
            entries.io.deq.ready := io.deq.ready
            io.count := entries.io.count
            proofOut.get := entries.io.deq.bits.proof
            proofOut.get.valid := entries.io.deq.valid && entries.io.deq.bits.proof.valid
        case None =>
            val entries = Module(new Queue(new DataRequest(p.dataReturnHandleBits),
                p.memoryEntries, pipe = false, flow = false, useSyncReadMem = false))
            io <> entries.io
    }
}
