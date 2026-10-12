package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import _root_.ooo.CanonicalStoreFixture

/** Boundary check with the real tracker and registered row payloads. Explicit 64-bit
  * tags cover the high-bit boundary; real backend binding supplies natural ROB reuse.
  * This fixture is not a replacement ROB or an independent permission oracle.
  */
class CanonicalStoreOwnerMapGsim(rows: Int = 16) extends Module {
    val p = CanonicalStoreFixture.params().copy(robEntries = rows, tagBits = 64)
    val io = IO(new Bundle {
        val staged = Input(Bool())
        val reconstruct = Input(Bool())
        val indexedTagXor = Input(UInt(64.W))
        val allocate = Input(Valid(new RobToken(p)))
        // memory, store, atomic, system; allocation alone makes a row live.
        val allocateClass = Input(UInt(4.W))
        val clear = Input(UInt(rows.W))
        val start = Input(Valid(new CanonicalStoreDescriptor(p)))
        val checked = Input(Valid(new CanonicalStoreCertificate(p)))
        val memoryProtected = Input(Bool())
        val memoryOwner = Input(new RobToken(p))
        val headValid = Input(Bool())
        val headDone = Input(Bool())
        val headOwner = Input(new RobToken(p))
        val retire = Input(Valid(new RobToken(p)))
        val complete = Input(Valid(new RobToken(p)))
        val exception = Input(Bool())
        val invalidate = Input(Bool())
        val stable = Input(Bool())
        val epoch = Input(UInt(32.W))
        val tracked = Output(Bool())
        val ownerLive = Output(Bool())
        val certificate = Output(Valid(new CanonicalStoreCertificate(p)))
        val reference = Output(UInt(rows.W))
        val candidate = Output(UInt(rows.W))
        val live = Output(UInt(rows.W))
        val pending = Output(UInt(rows.W))
    })
    val tokens = Reg(Vec(rows, new RobToken(p)))
    val classes = Reg(Vec(rows, UInt(4.W)))
    val live = RegInit(VecInit(Seq.fill(rows)(false.B)))
    val pending = RegInit(VecInit(Seq.fill(rows)(false.B)))
    val current = WireDefault(tokens)
    for (i <- 0 until rows) {
        current(i).index := Mux(io.reconstruct, i.U, tokens(i).index)
        current(i).tag := tokens(i).tag ^ io.indexedTagXor
    }
    val tracker = Module(new CanonicalStoreTracker(p))
    val token = tracker.io.owner
    val index = Mux(tracker.io.tracked, token.index, 0.U)
    // Keep the production integration's full indexed owner relation, all 64 tag bits.
    tracker.io.ownerLive := tracker.io.tracked && io.memoryProtected && io.headValid &&
        (!io.staged || !io.headDone) &&
        io.memoryOwner.asUInt === token.asUInt && io.headOwner.asUInt === token.asUInt &&
        live(index) && !pending(index) && current(index).asUInt === token.asUInt &&
        classes(index)(0) && classes(index)(1) && !classes(index)(2) && !classes(index)(3)
    tracker.io.start := io.start
    tracker.io.checked := io.checked
    tracker.io.stable := io.stable
    tracker.io.epoch := io.epoch
    val retired = io.retire.valid && io.retire.bits.asUInt === token.asUInt
    val disposed = io.complete.valid && (io.staged || io.exception) &&
        io.complete.bits.asUInt === token.asUInt
    tracker.io.invalidate := io.invalidate ||
        (tracker.io.tracked && (io.clear(index) || retired || disposed))
    for (i <- 0 until rows) {
        when(io.clear(i) || (io.retire.valid && io.retire.bits.index === i.U)) { live(i) := false.B }
        when(io.clear(i)) { pending(i) := false.B }
        when(live(i)) { assert(current(i).index === i.U, "only live rows have an indexed-token invariant") }
    }
    when(io.start.valid) { pending(io.start.bits.origin.token.index) := false.B }
    // Match production assignment priority: rename wins same-edge clears/starts.
    when(io.allocate.valid) {
        tokens(io.allocate.bits.index) := io.allocate.bits
        when(io.reconstruct) { tokens(io.allocate.bits.index).index := 0.U }
        classes(io.allocate.bits.index) := io.allocateClass
        live(io.allocate.bits.index) := io.allocateClass(0)
        pending(io.allocate.bits.index) := true.B
    }
    val certificate = tracker.io.certificate
    val reference = VecInit((0 until rows).map(i => certificate.valid && live(i) &&
        classes(i)(0) && classes(i)(1) && !classes(i)(2) &&
        current(i).asUInt === certificate.bits.origin.token.asUInt))
    val candidate = VecInit((0 until rows).map(i => certificate.valid && live(i) &&
        classes(i)(0) && classes(i)(1) && !classes(i)(2) &&
        certificate.bits.origin.token.index === i.U))
    assert(reference.asUInt === candidate.asUInt, "canonical consumer map differs from old full-token body")
    io.tracked := tracker.io.tracked
    io.ownerLive := tracker.io.ownerLive
    io.certificate := certificate
    io.reference := reference.asUInt
    io.candidate := candidate.asUInt
    io.live := live.asUInt
    io.pending := pending.asUInt
}

/** Test-only passive binding to the actual IntegerBackend. Never feeds ownerLive,
  * completion acceptance, start authorization, or any other production input.
  */
object CanonicalStoreOwnerMapBackendCheck {
    def attach(backend: IntegerBackend): UInt = {
        val p = backend.p
        val actual = VecInit(backend.certFor.map(BoringUtils.bore(_))).asUInt
        backend.canonicalStoreTracker.foreach { tracker =>
            val cert = BoringUtils.bore(tracker.io.certificate)
            val live = BoringUtils.bore(backend.memoryLive)
            val entries = (0 until p.robEntries).map(i => BoringUtils.bore(backend.issueEntries(i)))
            val reference = VecInit((0 until p.robEntries).map { i =>
                when(live(i)) { assert(entries(i).renamed.token.index === i.U,
                    "real backend live row lost its fixed token index") }
                cert.valid && live(i) && entries(i).request.memory && entries(i).request.store &&
                    !entries(i).request.atomic &&
                    entries(i).renamed.token.asUInt === cert.bits.origin.token.asUInt
            }).asUInt
            assert(actual === reference, "actual certFor differs from frozen full-token definition")
            val owner = BoringUtils.bore(tracker.io.owner)
            val ownerLive = BoringUtils.bore(tracker.io.ownerLive)
            when(cert.valid) {
                assert(ownerLive)
                assert(owner.asUInt === cert.bits.origin.token.asUInt)
                val indexed = VecInit(entries.map(_.renamed.token))(cert.bits.origin.token.index)
                assert(indexed.asUInt === cert.bits.origin.token.asUInt,
                    "certificate must retain actual indexed full-token producer authority")
            }
        }
        if (!p.canonicalVirtualStoreOverlap) { assert(actual === 0.U) }
        actual
    }
}

