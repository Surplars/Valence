package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import soc.ip.bus.MirroredHeadQueue

/** Exact-cycle parity plus an independent host FIFO; full native proof record. */
class MirroredRequestQueueGsim(depth: Int) extends Module {
    val p = ThreeProofRowNativeProfile.config.coreParams
    val width = (new RegisteredRequestEntry(p)).getWidth
    println(s"MIRRORED_REQUEST_RECORD_BITS=$width DEPTH=$depth")
    val io = IO(new Bundle {
        val push = Input(Bool()); val pop = Input(Bool()); val seed = Input(UInt(64.W))
        val ready = Output(Bool()); val valid = Output(Bool()); val count = Output(UInt(8.W))
        val data = Output(UInt(64.W)); val corrupt = Input(Bool())
    })
    val candidate = Module(new MirroredHeadQueue(UInt(width.W), depth, (width - 184 until width) :+ 139))
    val baseline = Module(new Queue(UInt(width.W), depth, pipe = false, flow = false))
    val payload = Cat((0 until ((width + 63) / 64)).reverse.map(i => io.seed ^ (BigInt(i) << 32).U(64.W)))(width-1, 0)
    for (queue <- Seq(candidate.io, baseline.io)) {
        queue.enq.valid := io.push; queue.deq.ready := io.pop; queue.enq.bits := payload
    }
    baseline.io.enq.bits := payload ^ (io.corrupt.asUInt << (width - 1))
    assert(candidate.io.enq.ready === baseline.io.enq.ready && candidate.io.deq.valid === baseline.io.deq.valid &&
        candidate.io.count === baseline.io.count, "mirrored queue handshake parity")
    when(candidate.io.deq.valid) {
        assert(candidate.io.deq.bits === baseline.io.deq.bits, "mirrored queue complete owner payload parity")
    }
    if (depth == p.memoryEntries) {
        val actual = Module(new RegisteredRequestQueue(p, projectedHead = true))
        val original = Module(new RegisteredRequestQueue(p))
        val entry = payload.asTypeOf(new RegisteredRequestEntry(p))
        for (q <- Seq(actual, original)) {
            q.io.enq.valid := io.push; q.io.enq.bits := entry.request; q.io.deq.ready := io.pop
            q.proofIn.foreach(_ := entry.postedProof.get)
            q.canonicalOriginIn.foreach(_ := entry.canonicalStoreOrigin.get)
            q.frozenProofIn.foreach(_ := entry.frozenStoreProof.get)
        }
        assert(actual.io.enq.ready === original.io.enq.ready && actual.io.deq.valid === original.io.deq.valid &&
            actual.io.count === original.io.count, "actual request wrapper handshake parity")
        when(actual.io.deq.valid) {
            assert(actual.io.deq.bits.asUInt === original.io.deq.bits.asUInt, "actual request payload parity")
            actual.proofOut.foreach(x => assert(x.asUInt === original.proofOut.get.asUInt, "posted owner parity"))
            actual.canonicalOriginOut.foreach(x => assert(x.asUInt === original.canonicalOriginOut.get.asUInt, "canonical owner parity"))
            actual.frozenProofOut.foreach(x => assert(x.asUInt === original.frozenProofOut.get.asUInt, "frozen owner parity"))
        }
    }
    io.ready := candidate.io.enq.ready; io.valid := candidate.io.deq.valid
    io.count := candidate.io.count; io.data := candidate.io.deq.bits(63, 0)
}
object MirroredRequestQueueGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MirroredRequestQueueGsim(args(1).toInt), Array("--target-dir", args(0)))
}

/** Mapping-only probe: exact native record width, all input/output bits retained. */
class MirroredRequestQueueMap(mirror: Boolean) extends Module {
    val width = (new RegisteredRequestEntry(ThreeProofRowNativeProfile.config.coreParams)).getWidth
    val io = IO(new QueueIO(UInt(width.W), 4))
    val q: QueueIO[UInt] = if (mirror) Module(new MirroredHeadQueue(UInt(width.W), 4, (width - 184 until width) :+ 139)).io
        else Module(new Queue(UInt(width.W), 4, pipe = false, flow = false)).io
    io <> q
}
object MirroredRequestQueueMapMain extends App {
    ChiselStage.emitCHIRRTLFile(new MirroredRequestQueueMap(args(1) == "1"), Array("--target-dir", args(0)))
}
