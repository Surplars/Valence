package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Public ordinary-access stimulus. Optional production proof envelopes stay invalid. */
class BufferedReturnOperation(p: OooParams) extends Bundle {
    val forward = Valid(UInt(64.W))
    val token = new RobToken(p)
    val pc = UInt(64.W)
    val address = UInt(64.W)
    val data = UInt(64.W)
    val atomic = Bool()
    val atomicOp = UInt(5.W)
    val store = Bool()
    val size = UInt(2.W)
    val unsigned = Bool()
    val accessDenied = Bool()
    val virtualized = Bool()
    val precheckedLoad = Bool()
    val physicalAddress = UInt(64.W)
    val translationEpoch = UInt(32.W)
}

/** Actual return consumers and storage, not a substitute for DTA/full CPU integration.
  * Integer: ParallelLSU -> registered requests -> StoreBuffer -> outer response buffer.
  * FP: actual registered FP pipeline -> the same outer response buffer in a drained domain.
  * External responses are independently supplied by the host; no translation is modeled here.
  */
class BufferedReturnChainGsim(enabled: Boolean) extends Module {
    val p = (if (enabled) CommonA1RebuildProfile.FullR1M3BufferedReturnFlow
        else CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof).config.coreParams
    require(p.memoryEntries == 4 && p.tagBits == 64 && p.robEntries == 16)
    require(p.registeredMemoryRequests && p.registeredStoreResponseOwners && !p.registeredLocalStoreResponses)
    require(!p.taggedStoreReturns && !p.fastHeadLoadRetire && !p.registeredLoadResultReady)
    val io = IO(new Bundle {
        val start = Flipped(Decoupled(new BufferedReturnOperation(p)))
        val parallel = Input(Bool())
        val cancel = Input(UInt(4.W))
        val complete = Decoupled(new BackendCompletion(p))
        val startSlots = Output(UInt(4.W))
        val live = Output(UInt(4.W))
        val discarded = Output(Bool())
        val requestOwned = Output(Bool())
        val requestToken = Output(new RobToken(p))
        val integerReply = Output(Bool())
        val fastStore = Flipped(Decoupled(new DataRequest))
        val fpMode = Input(Bool())
        // Scalar command avoids exposing the simulator's top-level Vec accessor ABI.
        val fpValid = Input(Bool())
        val fpReady = Output(Bool())
        val fpToken = Input(new RobToken(p))
        val fpInstruction = Input(UInt(32.W))
        val fpAddress = Input(UInt(64.W))
        val fpData = Input(UInt(64.W))
        val fpPc = Input(UInt(64.W))
        val fpComplete = Decoupled(new BackendCompletion(p))
        val fpBusy = Output(Bool())
        val memory = new DataPort
        val integerBusy = Output(Bool())
        val bufferIdle = Output(Bool())
        val allIdle = Output(Bool())
    })
    val lsu = Module(new ParallelLoadStoreUnit(p))
    val requests = Module(new RegisteredRequestQueue(p))
    val stores = Module(new StoreBuffer(p))
    val responses = Module(new DataResponseBuffer(registerPayload = true, registerHead = true, emptyFlow = enabled))
    lsu.io.start.valid := io.start.valid
    io.start.ready := lsu.io.start.ready
    lsu.io.start.bits := 0.U.asTypeOf(new MemoryOperation(p))
    for ((name, field) <- io.start.bits.elements) { lsu.io.start.bits.elements(name) := field }
    lsu.io.parallel := io.parallel
    lsu.io.cancel := VecInit((0 until 4).map(i => io.cancel(i)))
    lsu.io.fastStoreRetire := false.B
    lsu.io.fastLoadRetire := false.B
    lsu.io.issueDestination.foreach(_ := 0.U.asTypeOf(Valid(UInt(p.physBits.W))))
    lsu.io.relaxStoreOwner.foreach(_ := 0.U.asTypeOf(Valid(new RobToken(p))))
    lsu.io.boundHeadStoreOverlapQualified.foreach(_ := false.B)
    lsu.io.candidateAdmission.foreach { admission =>
        admission.precheckedLoad := false.B
        admission.parallel := io.parallel
    }
    io.complete <> lsu.io.complete
    requests.io.enq <> lsu.io.memory.request
    stores.io.upstream.request <> requests.io.deq
    stores.io.upstream.request.bits.size := Mux(requests.io.deq.valid, requests.io.deq.bits.size, 0.U)
    stores.io.upstream.response <> lsu.io.memory.response
    requests.proofIn.foreach(_ := lsu.io.postedProof.get)
    stores.io.upstreamProof.foreach(_ := requests.proofOut.get)
    requests.canonicalOriginIn.foreach(_ := lsu.io.canonicalStoreOrigin.get)
    stores.io.upstreamCanonicalStoreOrigin.foreach(_ := requests.canonicalOriginOut.get)
    requests.frozenProofIn.foreach(_ := lsu.io.frozenStoreProof.get)
    stores.io.upstreamFrozenStoreProof.foreach(_ := requests.frozenProofOut.get)
    stores.io.fastProof.foreach(_ := 0.U.asTypeOf(stores.io.fastProof.get))
    stores.io.externalPostedBusy.foreach(_ := false.B)
    stores.io.fastStore <> io.fastStore
    io.startSlots := VecInit(lsu.slots.map(slot =>
        BoringUtils.bore(slot.io.start.valid) && BoringUtils.bore(slot.io.start.ready))).asUInt
    io.live := lsu.io.live.asUInt
    io.discarded := lsu.io.discarded
    io.requestOwned := lsu.io.memory.request.fire
    io.requestToken := lsu.io.requestOwner.bits
    io.integerReply := lsu.io.memory.response.fire
    io.integerBusy := lsu.io.busy || stores.io.busy || requests.io.count =/= 0.U

    val fp = Module(new FloatingPointMemoryPipeline(p))
    fp.io.execute.valid := io.fpValid && io.fpMode
    fp.io.execute.bits := 0.U.asTypeOf(new FloatingPointExecution(p))
    fp.io.execute.bits.command.token := io.fpToken
    fp.io.execute.bits.command.instruction := io.fpInstruction
    fp.io.execute.bits.command.integerSource := io.fpAddress
    fp.io.execute.bits.operands(1) := io.fpData
    fp.io.pc := io.fpPc
    fp.io.trap := false.B
    fp.io.pmpState := 0.U.asTypeOf(new PmpState)
    fp.io.dataPrivilege := 3.U
    fp.io.virtualized := false.B
    io.fpReady := fp.io.execute.ready && io.fpMode
    io.fpComplete <> fp.io.complete
    io.fpBusy := fp.io.busy
    responses.io.upstream.request.valid := Mux(io.fpMode, fp.io.memory.request.valid, stores.io.memory.request.valid)
    responses.io.upstream.request.bits := Mux(io.fpMode, fp.io.memory.request.bits, stores.io.memory.request.bits)
    fp.io.memory.request.ready := io.fpMode && responses.io.upstream.request.ready
    stores.io.memory.request.ready := !io.fpMode && responses.io.upstream.request.ready
    fp.io.memory.response.valid := io.fpMode && responses.io.upstream.response.valid
    fp.io.memory.response.bits := responses.io.upstream.response.bits
    stores.io.memory.response.valid := !io.fpMode && responses.io.upstream.response.valid
    stores.io.memory.response.bits := responses.io.upstream.response.bits
    responses.io.upstream.response.ready := Mux(io.fpMode, fp.io.memory.response.ready, stores.io.memory.response.ready)
    io.memory <> responses.io.downstream
    io.bufferIdle := responses.io.idle
    io.allIdle := !io.integerBusy && !fp.io.busy && responses.io.idle
    when(io.start.valid) {
        assert(!io.start.bits.precheckedLoad && !io.start.bits.virtualized,
            "component ordinary physical stimulus supplies no independent translation permission")
    }
    when(io.fpMode) { assert(!io.integerBusy && !io.start.valid && !io.fastStore.valid) }
    val previousMode = RegNext(io.fpMode, false.B)
    when(previousMode =/= io.fpMode) { assert(io.allIdle, "test domain changes require complete consumer drain") }
}

object BufferedReturnChainGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new BufferedReturnChainGsim(args(1) == "1"), Array("--target-dir", args(0)))
}
