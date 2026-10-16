package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Passive test-only observer, identical on the pinned baseline and reconstructed candidate.
  * A shifting reference ledger checks the real FIFO boundary, including invalid metadata.
  * It neither gates traffic nor clears accepted ownership on cancellation.
  */
class RecoveredAtomicBackendGsim extends ReadyStoreQuery77BackendGsim(true, proofRows = 3,
    preselectRedirectTokenMatches = true, shadowEarlyProofBind = true,
    proofControlInputs = true, proofBankQuiesceIntent = true, proofBankOwnerCleanup = true) {
    override def desiredName: String = "ReadyStoreQuery77BackendGsim"
    require(p == ThreeProofRowNativeProfile.config.coreParams && p.memoryEntries == 4)
    class Transport extends Bundle {
        val request = new DataRequest(p.dataReturnHandleBits)
        val posted = Valid(new PostedStoreProof(p.postedProofConfig.get))
        val canonical = Valid(new CanonicalStoreOrigin(p))
        val frozen = Valid(new FrozenStoreProof)
    }
    val audit = IO(Output(new Bundle {
        val accepted = UInt(32.W)
        val drained = UInt(32.W)
        val stalled = UInt(32.W)
        val cancelledQueued = UInt(32.W)
        val cancelledResident = UInt(32.W)
        val canonical = UInt(32.W)
        val frozen = UInt(32.W)
        val posted = UInt(32.W)
    }))
    def tap[T <: Data](value: T): T = BoringUtils.bore(value)
    val q = backend.observationRequests.get
    val stores = backend.observationStores.get
    val offered = tap(q.io.enq.valid)
    val ready = tap(q.io.enq.ready)
    val present = tap(q.io.deq.valid)
    val downstreamReady = tap(q.io.deq.ready)
    val push = offered && ready
    val pop = present && downstreamReady
    val incoming = Wire(new Transport)
    incoming.request := tap(q.io.enq.bits)
    incoming.posted := tap(backend.lsu.io.postedProof.get)
    incoming.canonical := tap(backend.lsu.io.canonicalStoreOrigin.get)
    incoming.frozen := tap(backend.lsu.io.frozenStoreProof.get)
    val outgoing = Wire(new Transport)
    outgoing.request := tap(q.io.deq.bits)
    outgoing.posted := tap(stores.io.upstreamProof.get)
    outgoing.canonical := tap(stores.io.upstreamCanonicalStoreOrigin.get)
    outgoing.frozen := tap(stores.io.upstreamFrozenStoreProof.get)
    val saved = Reg(Vec(4, new Transport))
    val count = RegInit(0.U(3.W))
    assert(ready === (count < 4.U) && present === (count =/= 0.U), "independent FIFO timing/capacity")
    assert(tap(q.io.count) === count, "independent FIFO occupancy")
    when(present) {
        assert(outgoing.asUInt === saved(0).asUInt, "real FIFO complete request and sidecar ownership")
    }
    when(pop) { for (i <- 0 until 3) { saved(i) := saved(i + 1) } }
    when(push) { saved((count - pop.asUInt)(1, 0)) := incoming }
    when(push =/= pop) { count := Mux(push, count + 1.U, count - 1.U) }
    val cancel = tap(backend.lsu.io.cancel).asUInt
    val cancelledQueued = (0 until 4).map(i => i.U < count &&
        cancel(saved(i).request.returnHandle.get)).reduce(_ || _)
    val resident = VecInit(backend.lsu.slots.map(s => tap(s.io.busy))).asUInt
    def events(event: Bool): UInt = {
        val value = RegInit(0.U(32.W))
        when(event) { value := value + 1.U }
        value
    }
    audit.accepted := events(push)
    audit.drained := events(pop)
    audit.stalled := events(present && !downstreamReady)
    audit.cancelledQueued := events(cancelledQueued)
    audit.cancelledResident := events((cancel & resident).orR)
    audit.canonical := events(push && incoming.canonical.valid)
    audit.frozen := events(push && incoming.frozen.valid)
    audit.posted := events(push && incoming.posted.valid)
}

object RecoveredAtomicBackendMain extends App {
    require(args.length == 1)
    val out = Paths.get(args(0)); require(!Files.exists(out), "fresh output required")
    var actual: Option[OooParams] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = new RecoveredAtomicBackendGsim
        actual = Some(dut.backend.p)
        dut
    }, Array("--target-dir", out.toString))
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(actual.get) + "\n")
    Files.writeString(out.resolve("profile-shape.txt"), "board=95 core=178 rows=3 credits=2 lsu=4\n")
}
