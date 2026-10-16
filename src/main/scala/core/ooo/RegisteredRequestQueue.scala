package soc.core.ooo

import chisel3._
import chisel3.util._

/** One entry owns the complete request and every enabled request-synchronous sidecar.
  * Each optional Valid is independent: canonical/frozen ownership does not require posted authority.
  * Keep the native types intact, including return handles, full tokens, epochs and permissions.
  */
class RegisteredRequestEntry(p: OooParams) extends Bundle {
    val request = new DataRequest(p.dataReturnHandleBits)
    val postedProof = p.postedProofConfig.map(c => Valid(new PostedStoreProof(c)))
    val canonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap) Some(Valid(new CanonicalStoreOrigin(p))) else None
    val frozenStoreProof = if (p.frozenStoreProofEnabled) Some(Valid(new FrozenStoreProof)) else None
}

/** Request and all CPU proofs cross the same existing FIFO boundary atomically.
  * Capacity/latency/ready are exactly Queue(pipe=false, flow=false): no bypass,
  * no full dequeue-to-enqueue ready path, and one transfer per cycle after fill.
  * Capacity remains p.memoryEntries (four in the target profile), with one shared
  * pointer pair and handshake. Flush/quiesce do not erase an already accepted LSU
  * response owner. Acceptance and downstream authorization gates remain outside;
  * cancelled speculative reads still drain their physical responses normally.
  */
class RegisteredRequestQueue(p: OooParams) extends Module {
    val io = IO(new QueueIO(new DataRequest(p.dataReturnHandleBits), p.memoryEntries))
    val proofIn = p.postedProofConfig.map(c => IO(Input(Valid(new PostedStoreProof(c)))))
    val proofOut = p.postedProofConfig.map(c => IO(Output(Valid(new PostedStoreProof(c)))))
    val canonicalOriginIn = if (p.canonicalVirtualStoreOverlap)
        Some(IO(Input(Valid(new CanonicalStoreOrigin(p))))) else None
    val canonicalOriginOut = if (p.canonicalVirtualStoreOverlap)
        Some(IO(Output(Valid(new CanonicalStoreOrigin(p))))) else None
    val frozenProofIn = if (p.frozenStoreProofEnabled) Some(IO(Input(Valid(new FrozenStoreProof)))) else None
    val frozenProofOut = if (p.frozenStoreProofEnabled) Some(IO(Output(Valid(new FrozenStoreProof)))) else None

    val entries = Module(new Queue(new RegisteredRequestEntry(p), p.memoryEntries,
        pipe = false, flow = false, useSyncReadMem = false))
    entries.io.enq.valid := io.enq.valid
    entries.io.enq.bits.request := io.enq.bits
    entries.io.enq.bits.postedProof.foreach(_ := proofIn.get)
    entries.io.enq.bits.canonicalStoreOrigin.foreach(_ := canonicalOriginIn.get)
    entries.io.enq.bits.frozenStoreProof.foreach(_ := frozenProofIn.get)
    io.enq.ready := entries.io.enq.ready
    io.deq.valid := entries.io.deq.valid
    io.deq.bits := entries.io.deq.bits.request
    entries.io.deq.ready := io.deq.ready
    io.count := entries.io.count
    proofOut.foreach { proof =>
        proof := entries.io.deq.bits.postedProof.get
        proof.valid := entries.io.deq.valid && entries.io.deq.bits.postedProof.get.valid
    }
    canonicalOriginOut.foreach { origin =>
        origin := entries.io.deq.bits.canonicalStoreOrigin.get
        origin.valid := entries.io.deq.valid && entries.io.deq.bits.canonicalStoreOrigin.get.valid
    }
    frozenProofOut.foreach { proof =>
        proof := entries.io.deq.bits.frozenStoreProof.get
        proof.valid := entries.io.deq.valid && entries.io.deq.bits.frozenStoreProof.get.valid
    }
}
