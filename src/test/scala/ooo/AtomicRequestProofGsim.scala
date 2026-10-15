package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Frozen 22bbd0db FIFO wiring versus the production candidate, plus an external
  * host deque oracle. Both unchanged sidecars follow fire, including invalid proof.
  */
class AtomicRequestProofGsim extends Module {
    val p = ThreeProofRowNativeProfile.config.coreParams
    val c = p.postedProofConfig.get
    require(p.memoryEntries == 4 && p.dataReturnHandleBits > 0)
    val io = IO(new Bundle {
        val valid = Input(Bool())
        val ready = Input(Bool())
        val id = Input(UInt(64.W))
        val proofValid = Input(Bool())
        val flags = Input(UInt(6.W))
        val flush = Input(Bool())
        val quiesce = Input(Bool())
        val enqReady = Output(Bool())
        val deqValid = Output(Bool())
        val count = Output(UInt(3.W))
        val outId = Output(UInt(64.W))
        val outHandle = Output(UInt(p.dataReturnHandleBits.W))
        val outProofValid = Output(Bool())
        val outTag = Output(UInt(64.W))
        val outFlags = Output(UInt(6.W))
        val outOrigin = Output(UInt(64.W))
        val outFrozen = Output(UInt(64.W))
    })
    // flush/quiesce are observations only: original FIFO has neither clear nor
    // admission control. Upstream owns admission; already accepted owners drain.
    dontTouch(io.flush); dontTouch(io.quiesce)
    val request = WireDefault(0.U.asTypeOf(new DataRequest(p.dataReturnHandleBits)))
    request.address := "h80200000".U + (io.id(15, 0) << 3)
    request.data := io.id
    request.returnHandle.get := io.id
    request.atomic := !io.proofValid && io.id(4)
    request.atomicOp := io.id
    request.virtualized := !io.proofValid && io.id(5)
    request.precheckedLoad := !io.proofValid && io.id(6)
    request.uncached := !io.proofValid && io.id(7)
    request.write := io.proofValid || io.id(2)
    request.size := 3.U
    request.mask := 255.U
    request.translationEpoch := io.id(31, 0)
    request.prefetchNextAllowed := io.id(8)
    val proof = WireDefault(0.U.asTypeOf(Valid(new PostedStoreProof(c))))
    proof.valid := io.proofValid
    proof.bits.token.index := io.id
    proof.bits.token.tag := io.id ^ "hdecaf123456789ab".U
    proof.bits.epoch := io.id(31, 0)
    proof.bits.address := request.address
    proof.bits.data := request.data
    proof.bits.mask := request.mask
    proof.bits.size := request.size
    proof.bits.headAuthorized := io.flags(0)
    proof.bits.physicalPmpAllowed := io.flags(1)
    proof.bits.originalPhysical := io.flags(2)
    proof.bits.integerOrigin := io.flags(3)
    proof.bits.legacyPostedAccepted := io.flags(4)
    proof.bits.finalChecked := io.flags(5)

    val legacy = Module(new Queue(new DataRequest(p.dataReturnHandleBits), 4, pipe = false, flow = false))
    val oldProof = Module(new Queue(Valid(new PostedStoreProof(c)), 4, pipe = false, flow = false))
    legacy.io.enq.valid := io.valid
    legacy.io.enq.bits := request
    legacy.io.deq.ready := io.ready
    oldProof.io.enq.valid := legacy.io.enq.fire
    oldProof.io.enq.bits := proof
    oldProof.io.deq.ready := legacy.io.deq.fire
    assert(oldProof.io.deq.valid === legacy.io.deq.valid, "frozen proof sidecar alignment")
    when(legacy.io.enq.fire) { assert(oldProof.io.enq.ready) }

    val candidate = Module(new RegisteredRequestQueue(p))
    candidate.io.enq.valid := io.valid
    candidate.io.enq.bits := request
    candidate.io.deq.ready := io.ready
    candidate.proofIn.get := proof
    val noProof = Module(new RegisteredRequestQueue(p.copy(postedStoreMerge = false,
        postedYoungerLoadSealDeferral = false, postedPrefetchHeadOffer = false,
        postedPreparationPriority = false)))
    noProof.io.enq.valid := io.valid
    noProof.io.enq.bits := request
    noProof.io.deq.ready := io.ready
    assert(noProof.io.enq.ready === legacy.io.enq.ready && noProof.io.deq.valid === legacy.io.deq.valid)
    assert(noProof.io.count === legacy.io.count)
    when(legacy.io.deq.valid) { assert(noProof.io.deq.bits.asUInt === legacy.io.deq.bits.asUInt) }
    assert(candidate.io.enq.ready === legacy.io.enq.ready, "A/B enqueue ready")
    assert(candidate.io.deq.valid === legacy.io.deq.valid, "A/B publish cycle")
    assert(candidate.io.count === legacy.io.count, "A/B occupancy")
    when(legacy.io.deq.valid) {
        assert(candidate.io.deq.bits.asUInt === legacy.io.deq.bits.asUInt, "A/B full request and return owner")
        assert(candidate.proofOut.get.asUInt === oldProof.io.deq.bits.asUInt, "A/B full saved proof")
    }
    assert(!candidate.proofOut.get.valid || candidate.io.deq.valid, "no early permission publish")
    // Exact production sidecar types and fire wiring on both arms. Test them even
    // when a profile would elaborate one OFF, without enabling new production modes.
    def sidecars(q: QueueIO[DataRequest]): (UInt, UInt) = {
        val origin = Module(new Queue(Valid(new CanonicalStoreOrigin(p)), 4, pipe = false, flow = false))
        val frozen = Module(new Queue(Valid(new FrozenStoreProof), 4, pipe = false, flow = false))
        origin.io.enq.valid := q.enq.fire
        origin.io.enq.bits.bits := io.id.asTypeOf(origin.io.enq.bits.bits)
        origin.io.enq.bits.valid := io.id(2)
        origin.io.deq.ready := q.deq.fire
        frozen.io.enq.valid := q.enq.fire
        frozen.io.enq.bits.bits := (~io.id).asTypeOf(frozen.io.enq.bits.bits)
        frozen.io.enq.bits.valid := io.id(3)
        frozen.io.deq.ready := q.deq.fire
        assert(origin.io.deq.valid === q.deq.valid, "canonical sidecar transfer alignment")
        assert(frozen.io.deq.valid === q.deq.valid, "frozen sidecar transfer alignment")
        when(q.enq.fire) { assert(origin.io.enq.ready && frozen.io.enq.ready) }
        (origin.io.deq.bits.asUInt, frozen.io.deq.bits.asUInt)
    }
    val oldSide = sidecars(legacy.io)
    val newSide = sidecars(candidate.io)
    when(candidate.io.deq.valid) {
        assert(oldSide._1 === newSide._1 && oldSide._2 === newSide._2, "A/B both full sidecar payloads")
    }
    io.enqReady := candidate.io.enq.ready
    io.deqValid := candidate.io.deq.valid
    io.count := candidate.io.count
    io.outId := candidate.io.deq.bits.data
    io.outHandle := candidate.io.deq.bits.returnHandle.get
    io.outProofValid := candidate.proofOut.get.valid
    io.outTag := candidate.proofOut.get.bits.token.tag
    io.outFlags := Cat(candidate.proofOut.get.bits.finalChecked,
        candidate.proofOut.get.bits.legacyPostedAccepted, candidate.proofOut.get.bits.integerOrigin,
        candidate.proofOut.get.bits.originalPhysical, candidate.proofOut.get.bits.physicalPmpAllowed,
        candidate.proofOut.get.bits.headAuthorized)
    io.outOrigin := newSide._1
    io.outFrozen := newSide._2
}

object AtomicRequestProofGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new AtomicRequestProofGsim, Array("--target-dir", args(0)))
}
