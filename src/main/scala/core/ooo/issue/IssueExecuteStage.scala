package soc.core.ooo

import chisel3._
import chisel3.util._

/** One operand/execution slot: capacity 1, minimum latency 1, sustained II 1.
  * No empty bypass. A consumed old owner can be replaced on the same edge.
  * Cancellation does NOT lend combinational input credit: a full stalled slot
  * that is cancelled becomes available next cycle. When the consumer is ready,
  * cancellation and replacement may still coincide. Cancellation concerns the
  * OLD owner only; the producer must independently authorize a replacement.
  * Payload stays stable under backpressure, including LSU/M/CSR arbitration.
  */
class IssueExecuteStage(payloadBits: Int) extends Module {
    require(payloadBits > 0)
    val io = IO(new Bundle {
        val enq = Flipped(Decoupled(UInt(payloadBits.W)))
        val deq = Decoupled(UInt(payloadBits.W))
        val cancel = Input(Bool())
        val occupied = Output(Bool())
    })
    val occupied = RegInit(false.B)
    val payload = RegInit(0.U(payloadBits.W))
    io.occupied := occupied
    // Late recovery authorization ends at the local valid register/output;
    // never feed its cancel signal back through credit into issue selection.
    io.enq.ready := !occupied || io.deq.ready
    io.deq.valid := occupied && !io.cancel
    io.deq.bits := payload
    when(io.cancel || io.deq.fire) { occupied := false.B }
    when(io.enq.fire) {
        occupied := true.B
        payload := io.enq.bits
    }
}

private[ooo] class IntegerExecutionOperands(p: OooParams) extends Bundle {
    val entry = new IntegerIssueEntry(p)
    val left = UInt(64.W)
    val right = UInt(64.W)
    val forwardable = Bool()
}
