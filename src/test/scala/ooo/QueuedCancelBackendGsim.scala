package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Test-only external ready/valid backpressure; no production owner or cancellation state is forced. */
class QueuedCancelBackendGsim extends RecoveredAtomicBackendGsim {
    val holdBackendMemory = IO(Input(Bool()))
    val queued = IO(Output(new Bundle {
        val count = UInt(3.W)
        val handles = UInt(4.W)
        val cancelledHandles = UInt(4.W)
    }))
    // Requests/sidecars cannot cross this existing external boundary while held.
    // Responses are never gated. Hold is asserted only while the boundary is idle.
    backend.io.memory.request.ready := responses.io.upstream.request.ready && !holdBackendMemory
    responses.io.upstream.request.valid := backend.io.memory.request.valid && !holdBackendMemory
    adapter.io.posted.get.upstreamProof.valid := backend.io.posted.get.requestProof.valid && !holdBackendMemory
    adapter.io.canonicalStoreOrigin.get.valid :=
        backend.io.canonicalStore.get.requestOrigin.valid && !holdBackendMemory
    adapter.io.frozenStoreProof.get.valid :=
        backend.io.canonicalStore.get.requestFrozenProof.get.valid && !holdBackendMemory
    val handles = (0 until 4).map(i => Mux(i.U < count,
        UIntToOH(saved(i).request.returnHandle.get, 4), 0.U(4.W))).reduce(_ | _)
    val cancelledHandles = RegInit(0.U(4.W))
    cancelledHandles := cancelledHandles | (handles & cancel)
    queued.count := count
    queued.handles := handles
    queued.cancelledHandles := cancelledHandles
}

object QueuedCancelBackendMain extends App {
    require(args.length == 1)
    val out = Paths.get(args(0)); require(!Files.exists(out), "fresh output required")
    var actual: Option[OooParams] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = new QueuedCancelBackendGsim
        actual = Some(dut.backend.p)
        dut
    }, Array("--target-dir", out.toString))
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(actual.get) + "\n")
}
