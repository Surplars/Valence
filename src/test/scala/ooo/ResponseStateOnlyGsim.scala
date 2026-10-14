package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import java.nio.file.{Files, Paths}

object ResponseStateOnlyConfig {
    def params(enabled: Boolean = true): OooParams = PendingStoreProofFixture.params().copy(
        boundHeadStoreOverlap = true,
        storeBufferEntries = 2, taggedStoreReturns = true, dataNextLinePrefetch = true,
        registeredStoreResponseOwners = true, registeredLocalStoreResponses = true,
        parallelPrfReadyUpdates = true, ownerLocalOperandReady = true, ownerLocalIssueReady = true,
        registeredIssueExecute = true, registeredLoadIssueForwarding = true, heldAluIssueForwarding = true,
        parallelIssuePayload = true, parallelIssueRanks = true, earlyRankedOperands = true,
        parallelRecoveryAdmission = true, lvtPhysicalRegisterFile = true,
        registeredBranchRedirect = true, precompleteMispredictedBranch = true,
        registeredRobRetirement = true, registeredLoadResultReady = true, localTaggedResponseReady = true)
}
class ResponseStateOnlyIO(p: OooParams) extends Bundle {
    val start = Flipped(Decoupled(new MemoryOperation(p)))
    val destination = Input(Valid(UInt(p.physBits.W)))
    // Component-interface contract only: the board profile keeps fast retirement disabled.
    val fastLoadRetire = Input(Bool())
    val completedDestination = Output(Valid(UInt(p.physBits.W)))
    val publish = Output(UInt(4.W)); val held = Output(UInt(4.W))
    val publishDestination0 = Output(UInt(p.physBits.W)); val publishDestination1 = Output(UInt(p.physBits.W))
    val publishDestination2 = Output(UInt(p.physBits.W)); val publishDestination3 = Output(UInt(p.physBits.W))
    val heldDestination0 = Output(UInt(p.physBits.W)); val heldDestination1 = Output(UInt(p.physBits.W))
    val heldDestination2 = Output(UInt(p.physBits.W)); val heldDestination3 = Output(UInt(p.physBits.W))
    val heldData0 = Output(UInt(64.W)); val heldData1 = Output(UInt(64.W))
    val heldData2 = Output(UInt(64.W)); val heldData3 = Output(UInt(64.W))
    val slotStart = Output(UInt(4.W)); val slotResponse = Output(UInt(4.W))
    val slotRequestValid = Output(UInt(4.W)); val slotRequestReady = Output(UInt(4.W))
    val parallel = Input(Bool()); val qualified = Input(Bool())
    val relax = Input(Valid(new RobToken(p)))
    val cancel = Input(UInt(4.W))
    val memory = new DataPort(p.dataReturnHandleBits)
    val complete = Decoupled(new BackendCompletion(p))
    val holdEnqueue = Input(Bool()); val holdQueue = Input(Bool()); val holdResponse = Input(Bool())
    // Drained-mode direct boundary exercises earliest offered same-edge reply.
    val directResponse = Input(Bool())
    val live = Output(UInt(4.W)); val phase = Output(UInt(8.W))
    val owner0 = Output(new RobToken(p)); val owner1 = Output(new RobToken(p))
    val owner2 = Output(new RobToken(p)); val owner3 = Output(new RobToken(p))
    val chosen = Output(UInt(2.W)); val available = Output(Bool())
    val overlapAccepted = Output(Bool()); val discarded = Output(Bool()); val forwarded = Output(Bool())
    val request = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
    val requestReady = Output(Bool()); val requestOwner = Output(Valid(new RobToken(p)))
    val origin = Output(Valid(new CanonicalStoreOrigin(p))); val frozen = Output(Valid(new FrozenStoreProof))
    val response = Output(Valid(new DataResponse(p.dataReturnHandleBits))); val responseReady = Output(Bool())
    val idle = Output(Bool())
}
class ResponseStateOnlyBoundary(enabled: Boolean) extends Module {
    val p = ResponseStateOnlyConfig.params(true)
    val io = IO(new ResponseStateOnlyIO(p))
    val lsu = Module(new ParallelLoadStoreUnit(p, canonicalHandoff = true, localTaggedResponseReady = true))
    val requests = Module(new Queue(new DataRequest(p.dataReturnHandleBits), p.memoryEntries, pipe = false, flow = false))
    val responses = Module(new DataResponseBuffer(registerPayload = true, registerHead = true, returnConfig = p.cpuReturnConfig))
    lsu.io.start <> io.start; lsu.io.complete <> io.complete
    lsu.io.parallel := io.parallel; lsu.io.boundHeadStoreOverlapQualified.get := io.qualified
    lsu.io.relaxStoreOwner.get := io.relax
    lsu.io.issueDestination.get := io.destination
    io.completedDestination := lsu.io.completedIssueDestination.get
    val publication = lsu.io.loadResultPublish.get
    val held = lsu.io.heldLoadValue.get
    io.publish := VecInit(publication.map(_.valid)).asUInt
    io.held := VecInit(held.map(_.valid)).asUInt
    Seq(io.publishDestination0, io.publishDestination1, io.publishDestination2, io.publishDestination3)
        .zipWithIndex.foreach { case (out, i) => out := publication(i).bits }
    Seq(io.heldDestination0, io.heldDestination1, io.heldDestination2, io.heldDestination3)
        .zipWithIndex.foreach { case (out, i) => out := held(i).bits.destination }
    Seq(io.heldData0, io.heldData1, io.heldData2, io.heldData3)
        .zipWithIndex.foreach { case (out, i) => out := held(i).bits.data }
    // Observations only: real public slot ports, with no forced internal ready/state.
    io.slotStart := VecInit(lsu.slots.map(s => (BoringUtils.bore(s.io.start.valid) && BoringUtils.bore(s.io.start.ready)))).asUInt
    io.slotResponse := VecInit(lsu.slots.map(s => (BoringUtils.bore(s.io.memory.response.valid) && BoringUtils.bore(s.io.memory.response.ready)))).asUInt
    io.slotRequestValid := VecInit(lsu.slots.map(s => BoringUtils.bore(s.io.memory.request.valid))).asUInt
    io.slotRequestReady := VecInit(lsu.slots.map(s => BoringUtils.bore(s.io.memory.request.ready))).asUInt
    lsu.io.cancel := VecInit((0 until 4).map(i => io.cancel(i)))
    lsu.io.fastStoreRetire := false.B; lsu.io.fastLoadRetire := io.fastLoadRetire
    requests.io.enq.bits := lsu.io.memory.request.bits
    requests.io.enq.valid := lsu.io.memory.request.valid && !io.holdEnqueue
    lsu.io.memory.request.ready := requests.io.enq.ready && !io.holdEnqueue
    responses.io.upstream.request.bits := requests.io.deq.bits
    responses.io.upstream.request.valid := requests.io.deq.valid && !io.holdQueue
    requests.io.deq.ready := responses.io.upstream.request.ready && !io.holdQueue
    io.memory.request <> responses.io.downstream.request
    responses.io.downstream.response.bits := io.memory.response.bits
    responses.io.downstream.response.valid := io.memory.response.valid && !io.directResponse
    io.memory.response.ready := Mux(io.directResponse, lsu.io.memory.response.ready && !io.holdResponse,
        responses.io.downstream.response.ready)
    lsu.io.memory.response.valid := Mux(io.directResponse, io.memory.response.valid,
        responses.io.upstream.response.valid) && !io.holdResponse
    lsu.io.memory.response.bits := Mux(io.directResponse, io.memory.response.bits, responses.io.upstream.response.bits)
    responses.io.upstream.response.ready := lsu.io.memory.response.ready && !io.directResponse && !io.holdResponse
    io.live := lsu.io.live.asUInt; io.phase := lsu.io.phase.asUInt
    Seq(io.owner0,io.owner1,io.owner2,io.owner3).zipWithIndex.foreach { case (out,i) => out := lsu.io.owner(i) }
    io.chosen := BoringUtils.bore(lsu.chosen); io.available := lsu.io.issueAvailable
    // Test-only replay of the exact pre-factor selection/availability equations.
    // Both sides are checked against real current slot state, not synthetic state.
    val oldEmpty = VecInit(lsu.io.live.map(live => !live))
    val observedParallel = BoringUtils.bore(lsu.parallel)
    val observedExempt = lsu.exemptSerial.map(x => BoringUtils.bore(x))
    val observedHandoff = BoringUtils.bore(lsu.handoffOffer)
    val observedBound = BoringUtils.bore(lsu.boundHeadStoreOverlapOffer)
    val observedCompletionValid = BoringUtils.bore(lsu.completion.io.out.valid)
    val observedCompletionChosen = BoringUtils.bore(lsu.completion.io.chosen)
    val oldChosen = Mux(observedHandoff || observedBound, PriorityEncoder(oldEmpty),
        Mux(observedCompletionValid, observedCompletionChosen, PriorityEncoder(oldEmpty)))
    val oldAvailable = observedCompletionValid || oldEmpty.asUInt.orR
    val oldOthersIdle = (0 until 4).map(i => oldChosen === i.U || oldEmpty(i)).reduce(_ && _)
    val oldNoOtherSerial = (0 until 4).map(i => oldEmpty(i) || observedParallel(i) ||
        (observedCompletionValid && oldChosen === i.U) || observedExempt(i)).reduce(_ && _)
    val oldIssueAvailable = oldAvailable && oldNoOtherSerial &&
        (io.parallel || oldOthersIdle || observedBound)
    val oldSelectedReady = Mux1H((0 until 4).map(i =>
        (oldChosen === i.U) -> BoringUtils.bore(lsu.slots(i).io.start.ready)))
    assert(io.chosen === oldChosen, "factored choice differs from exact old selection equation")
    assert(lsu.io.issueAvailable === oldIssueAvailable,
        "factored issue availability differs from exact old selection equation")
    assert(lsu.io.start.ready === (oldIssueAvailable && oldSelectedReady),
        "factored start ready differs from exact old selected-slot readiness")
    io.overlapAccepted := lsu.io.boundHeadStoreOverlapAccepted.get
    io.discarded := lsu.io.discarded; io.forwarded := lsu.io.forwarded
    io.request.valid := lsu.io.memory.request.valid; io.request.bits := lsu.io.memory.request.bits
    io.requestReady := lsu.io.memory.request.ready; io.requestOwner := lsu.io.requestOwner
    io.origin := lsu.io.canonicalStoreOrigin.get; io.frozen := lsu.io.frozenStoreProof.get
    io.response.valid := lsu.io.memory.response.valid; io.response.bits := lsu.io.memory.response.bits
    io.responseReady := lsu.io.memory.response.ready
    io.idle := !lsu.io.busy && requests.io.count === 0.U && responses.io.idle
}
class ResponseStateReferenceBoundary(enabled: Boolean) extends Module {
    val p = ResponseStateOnlyConfig.params(true)
    val io = IO(new ResponseStateOnlyIO(p))
    val lsu = Module(new ResponseStateReferenceParallelLoadStoreUnit(p, canonicalHandoff = true, localTaggedResponseReady = true))
    val requests = Module(new Queue(new DataRequest(p.dataReturnHandleBits), p.memoryEntries, pipe = false, flow = false))
    val responses = Module(new DataResponseBuffer(registerPayload = true, registerHead = true, returnConfig = p.cpuReturnConfig))
    lsu.io.start <> io.start; lsu.io.complete <> io.complete
    lsu.io.parallel := io.parallel; lsu.io.boundHeadStoreOverlapQualified.get := io.qualified
    lsu.io.relaxStoreOwner.get := io.relax
    lsu.io.issueDestination.get := io.destination
    io.completedDestination := lsu.io.completedIssueDestination.get
    val publication = lsu.io.loadResultPublish.get
    val held = lsu.io.heldLoadValue.get
    io.publish := VecInit(publication.map(_.valid)).asUInt
    io.held := VecInit(held.map(_.valid)).asUInt
    Seq(io.publishDestination0, io.publishDestination1, io.publishDestination2, io.publishDestination3)
        .zipWithIndex.foreach { case (out, i) => out := publication(i).bits }
    Seq(io.heldDestination0, io.heldDestination1, io.heldDestination2, io.heldDestination3)
        .zipWithIndex.foreach { case (out, i) => out := held(i).bits.destination }
    Seq(io.heldData0, io.heldData1, io.heldData2, io.heldData3)
        .zipWithIndex.foreach { case (out, i) => out := held(i).bits.data }
    // Observations only: real public slot ports, with no forced internal ready/state.
    io.slotStart := VecInit(lsu.slots.map(s => (BoringUtils.bore(s.io.start.valid) && BoringUtils.bore(s.io.start.ready)))).asUInt
    io.slotResponse := VecInit(lsu.slots.map(s => (BoringUtils.bore(s.io.memory.response.valid) && BoringUtils.bore(s.io.memory.response.ready)))).asUInt
    io.slotRequestValid := VecInit(lsu.slots.map(s => BoringUtils.bore(s.io.memory.request.valid))).asUInt
    io.slotRequestReady := VecInit(lsu.slots.map(s => BoringUtils.bore(s.io.memory.request.ready))).asUInt
    lsu.io.cancel := VecInit((0 until 4).map(i => io.cancel(i)))
    lsu.io.fastStoreRetire := false.B; lsu.io.fastLoadRetire := io.fastLoadRetire
    requests.io.enq.bits := lsu.io.memory.request.bits
    requests.io.enq.valid := lsu.io.memory.request.valid && !io.holdEnqueue
    lsu.io.memory.request.ready := requests.io.enq.ready && !io.holdEnqueue
    responses.io.upstream.request.bits := requests.io.deq.bits
    responses.io.upstream.request.valid := requests.io.deq.valid && !io.holdQueue
    requests.io.deq.ready := responses.io.upstream.request.ready && !io.holdQueue
    io.memory.request <> responses.io.downstream.request
    responses.io.downstream.response.bits := io.memory.response.bits
    responses.io.downstream.response.valid := io.memory.response.valid && !io.directResponse
    io.memory.response.ready := Mux(io.directResponse, lsu.io.memory.response.ready && !io.holdResponse,
        responses.io.downstream.response.ready)
    lsu.io.memory.response.valid := Mux(io.directResponse, io.memory.response.valid,
        responses.io.upstream.response.valid) && !io.holdResponse
    lsu.io.memory.response.bits := Mux(io.directResponse, io.memory.response.bits, responses.io.upstream.response.bits)
    responses.io.upstream.response.ready := lsu.io.memory.response.ready && !io.directResponse && !io.holdResponse
    io.live := lsu.io.live.asUInt; io.phase := lsu.io.phase.asUInt
    Seq(io.owner0,io.owner1,io.owner2,io.owner3).zipWithIndex.foreach { case (out,i) => out := lsu.io.owner(i) }
    io.chosen := BoringUtils.bore(lsu.chosen); io.available := lsu.io.issueAvailable
    // Test-only replay of the exact pre-factor selection/availability equations.
    // Both sides are checked against real current slot state, not synthetic state.
    val oldEmpty = VecInit(lsu.io.live.map(live => !live))
    val observedParallel = BoringUtils.bore(lsu.parallel)
    val observedExempt = lsu.exemptSerial.map(x => BoringUtils.bore(x))
    val observedHandoff = BoringUtils.bore(lsu.handoffOffer)
    val observedBound = BoringUtils.bore(lsu.boundHeadStoreOverlapOffer)
    val observedCompletionValid = BoringUtils.bore(lsu.completion.io.out.valid)
    val observedCompletionChosen = BoringUtils.bore(lsu.completion.io.chosen)
    val oldChosen = Mux(observedHandoff || observedBound, PriorityEncoder(oldEmpty),
        Mux(observedCompletionValid, observedCompletionChosen, PriorityEncoder(oldEmpty)))
    val oldAvailable = observedCompletionValid || oldEmpty.asUInt.orR
    val oldOthersIdle = (0 until 4).map(i => oldChosen === i.U || oldEmpty(i)).reduce(_ && _)
    val oldNoOtherSerial = (0 until 4).map(i => oldEmpty(i) || observedParallel(i) ||
        (observedCompletionValid && oldChosen === i.U) || observedExempt(i)).reduce(_ && _)
    val oldIssueAvailable = oldAvailable && oldNoOtherSerial &&
        (io.parallel || oldOthersIdle || observedBound)
    val oldSelectedReady = Mux1H((0 until 4).map(i =>
        (oldChosen === i.U) -> BoringUtils.bore(lsu.slots(i).io.start.ready)))
    assert(io.chosen === oldChosen, "factored choice differs from exact old selection equation")
    assert(lsu.io.issueAvailable === oldIssueAvailable,
        "factored issue availability differs from exact old selection equation")
    assert(lsu.io.start.ready === (oldIssueAvailable && oldSelectedReady),
        "factored start ready differs from exact old selected-slot readiness")
    io.overlapAccepted := lsu.io.boundHeadStoreOverlapAccepted.get
    io.discarded := lsu.io.discarded; io.forwarded := lsu.io.forwarded
    io.request.valid := lsu.io.memory.request.valid; io.request.bits := lsu.io.memory.request.bits
    io.requestReady := lsu.io.memory.request.ready; io.requestOwner := lsu.io.requestOwner
    io.origin := lsu.io.canonicalStoreOrigin.get; io.frozen := lsu.io.frozenStoreProof.get
    io.response.valid := lsu.io.memory.response.valid; io.response.bits := lsu.io.memory.response.bits
    io.responseReady := lsu.io.memory.response.ready
    io.idle := !lsu.io.busy && requests.io.count === 0.U && responses.io.idle
}
class ResponseStateOnlyGsim extends Module {
    val p = ResponseStateOnlyConfig.params()
    val io = IO(new ResponseStateOnlyIO(p))
    val on = Module(new ResponseStateOnlyBoundary(true)); val off = Module(new ResponseStateReferenceBoundary(true))
    io <> on.io
    val a = on.io; val b = off.io
    b.destination := a.destination; b.fastLoadRetire := a.fastLoadRetire
    b.start.valid := a.start.valid; b.start.bits := a.start.bits; b.parallel := a.parallel
    b.qualified := a.qualified; b.relax := a.relax; b.cancel := a.cancel
    b.memory.request.ready := a.memory.request.ready
    b.memory.response.valid := a.memory.response.valid; b.memory.response.bits := a.memory.response.bits
    b.complete.ready := a.complete.ready; b.holdEnqueue := a.holdEnqueue; b.holdQueue := a.holdQueue
    b.holdResponse := a.holdResponse; b.directResponse := a.directResponse
    def port(x: ReadyValidIO[_ <: Data], y: ReadyValidIO[_ <: Data], label: String): Unit = {
        assert(x.valid === y.valid && x.ready === y.ready, label + " handshake parity")
        when(x.valid) { assert(x.bits.asUInt === y.bits.asUInt, label + " complete valid tuple parity") }
    }
    def valid(x: ValidIO[_ <: Data], y: ValidIO[_ <: Data], label: String): Unit = {
        assert(x.valid === y.valid, label + " valid parity")
        when(x.valid) { assert(x.bits.asUInt === y.bits.asUInt, label + " complete valid tuple parity") }
    }
    port(a.start,b.start,"start"); port(a.memory.request,b.memory.request,"external request")
    port(a.memory.response,b.memory.response,"external response"); port(a.complete,b.complete,"completion")
    valid(a.request,b.request,"LSU enqueue"); valid(a.requestOwner,b.requestOwner,"request owner")
    valid(a.origin,b.origin,"canonical origin"); valid(a.frozen,b.frozen,"frozen proof")
    valid(a.response,b.response,"actual LSU response")
    valid(a.completedDestination,b.completedDestination,"completed destination")
    val initialized = RegInit(VecInit(Seq.fill(4)(false.B)))
    for (i <- 0 until 4) {
        when(a.slotStart(i)) { initialized(i) := true.B }
        assert(BoringUtils.bore(on.lsu.slots(i).cancelled) ===
            BoringUtils.bore(off.lsu.slots(i).cancelled), "saved cancellation state parity")
        when(initialized(i)) {
            assert(BoringUtils.bore(on.lsu.slots(i).result).asUInt ===
                BoringUtils.bore(off.lsu.slots(i).result).asUInt, "complete saved result state parity")
            assert(BoringUtils.bore(on.lsu.slots(i).operation).asUInt ===
                BoringUtils.bore(off.lsu.slots(i).operation).asUInt, "complete saved operation state parity")
        }
    }
    assert(a.publish === b.publish && a.held === b.held,"publication and held masks parity")
    val publishA = Seq(a.publishDestination0,a.publishDestination1,a.publishDestination2,a.publishDestination3)
    val publishB = Seq(b.publishDestination0,b.publishDestination1,b.publishDestination2,b.publishDestination3)
    val heldA = Seq(a.heldDestination0,a.heldDestination1,a.heldDestination2,a.heldDestination3)
    val heldB = Seq(b.heldDestination0,b.heldDestination1,b.heldDestination2,b.heldDestination3)
    val dataA = Seq(a.heldData0,a.heldData1,a.heldData2,a.heldData3)
    val dataB = Seq(b.heldData0,b.heldData1,b.heldData2,b.heldData3)
    for (i <- 0 until 4) {
        when(a.publish(i)) { assert(publishA(i) === publishB(i),"valid publication destination parity") }
        when(a.held(i)) {
            assert(heldA(i) === heldB(i) && dataA(i) === dataB(i),"valid held destination/data parity")
        }
    }
    assert(a.slotStart === b.slotStart && a.slotResponse === b.slotResponse &&
        a.slotRequestValid === b.slotRequestValid && a.slotRequestReady === b.slotRequestReady,
        "actual per-slot handshake parity")
    assert(a.requestReady === b.requestReady && a.responseReady === b.responseReady,"LSU ready parity including invalid cycles")
    assert(a.live === b.live && a.phase === b.phase && a.chosen === b.chosen && a.available === b.available &&
        a.overlapAccepted === b.overlapAccepted && a.discarded === b.discarded && a.forwarded === b.forwarded &&
        a.idle === b.idle,"lifecycle and ownership parity")
    Seq((a.owner0,b.owner0),(a.owner1,b.owner1),(a.owner2,b.owner2),(a.owner3,b.owner3)).zipWithIndex.foreach {
        case ((x,y),i) => when(a.live(i)) { assert(x.asUInt === y.asUInt,"live full-token owner parity") }
    }
}
object ResponseStateOnlyGsimMain extends App {
    require(args.length == 1, "output directory; this entry emits one paired model only")
    val on = ResponseStateOnlyConfig.params(true)
    val off = ResponseStateOnlyConfig.params(true)
    require(on == off,
        "both real tagged configurations are identical; only slot implementation differs")
    require(on.registeredLoadResultReady && off.registeredLoadResultReady &&
        on.memoryEntries == 4 && on.taggedStoreReturns && on.registeredLoadIssueForwarding)
    var rejectedFastProfile = false
    try { on.copy(fastHeadLoadRetire = true) }
    catch { case _: IllegalArgumentException => rejectedFastProfile = true }
    require(rejectedFastProfile, "registered-ready board profile must keep fast load retirement disabled")
    val dir = Paths.get(args(0))
    Files.createDirectories(dir)
    for ((label, p) <- Seq("on" -> on, "off" -> off)) {
        Files.writeString(dir.resolve(s"actual-core-$label.json"), PostedBoardConfiguration.json(p) + "\n")
    }
    ChiselStage.emitCHIRRTLFile(new ResponseStateOnlyGsim, Array("--target-dir", args(0)))
}
