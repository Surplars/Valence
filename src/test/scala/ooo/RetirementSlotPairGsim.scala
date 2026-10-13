package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}

object RetirementSlotTestProfile {
    val off: OooParams = _root_.ooo.RetirementSlotProfile.p
    val on: OooParams = off.copy(retirementSlotIdentity = true)
    def writeParameters(directory: String): Unit = _root_.ooo.RetirementSlotProfile.writeParameters(directory)
}

class RetirementOffer extends Bundle {
    val valid = Bool()
    val kind = UInt(3.W) // 0 add, 1 multiply, 2 divide, 3 branch, 4 system, 5 load, 6 fault
    val value = UInt(64.W)
    val instruction = UInt(32.W)
    val rd = UInt(5.W)
}
class RetirementObservation(p: OooParams) extends Bundle {
    val renamed0 = Valid(new RobToken(p))
    val renamed1 = Valid(new RobToken(p))
    val issued0 = Valid(new BackendCompletion(p))
    val issued1 = Valid(new BackendCompletion(p))
    val commit0 = Valid(new CommitRecord(p))
    val commit1 = Valid(new CommitRecord(p))
    val occupancy = UInt(p.countBits.W)
    val head = UInt(p.robBits.W)
    val recoveryCycle = Bool()
    val commitEnable = Bool()
    val recovery = Valid(new RecoveryRequest(p))
    val producers = UInt(5.W) // LSU, div, mul, system, held branch
    val execOccupied = UInt(2.W)
    val execReady = UInt(2.W)
    val execCancel = UInt(2.W)
    val execBranch = UInt(2.W)
    val actual = UInt(2.W)
    val intent = UInt(2.W)
    val retireClass = UInt(2.W)
    val retireFault = UInt(2.W)
    val qualified = UInt(2.W)
    val completion0 = new BackendCompletion(p)
    val completion1 = new BackendCompletion(p)
    val trap = Bool()
    val physicalWriteMask = UInt(2.W)
}
class RetirementSlotPairGsim extends Module {
    val p = RetirementSlotTestProfile.off
    val io = IO(new Bundle {
        val offer0 = Input(new RetirementOffer)
        val offer1 = Input(new RetirementOffer)
        val pc = Input(UInt(64.W))
        val commitEnable = Input(Bool())
        val memoryReady = Input(Bool())
        val memoryResponse = Input(Valid(new DataResponse(p.dataReturnHandleBits)))
        val memoryRequest = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
        val memoryResponseReady = Output(Bool())
        val reference = Output(new RetirementObservation(p))
        val candidate = Output(new RetirementObservation(p))
        val rob = new RetirementSlotRobPort(p)
    })
    val robPair = Module(new RetirementSlotRobGsim)
    io.rob <> robPair.io
    val requests = Seq(io.offer0, io.offer1).zipWithIndex.map { case (offer, lane) =>
        val request = WireDefault(0.U.asTypeOf(Valid(new IntegerRequest)))
        request.valid := offer.valid
        request.bits.rename.pc := io.pc + (4 * lane).U
        request.bits.rename.instruction := offer.instruction
        request.bits.expandedInstruction := offer.instruction
        request.bits.rename.rd := offer.rd
        request.bits.rename.writesRd := offer.rd =/= 0.U
        request.bits.system := offer.kind === 4.U
        request.bits.fetchFault := offer.kind === 6.U
        request.bits.fetchTval := io.pc + (4 * lane).U
        request.bits.operation := IntegerOp.add
        request.bits.useImmediate := true.B
        request.bits.immediate := offer.value
        request.bits.mulDiv := offer.kind === 1.U || offer.kind === 2.U
        request.bits.mulDivOp := Mux(offer.kind === 2.U, 4.U, 0.U)
        request.bits.controlFlow := Mux(offer.kind === 3.U, ControlFlow.beq, ControlFlow.none)
        request.bits.memory := offer.kind === 5.U
        request.bits.memorySize := 3.U
        request
    }
    val backends = Seq(false, true).map { enabled =>
        val params = if (enabled) RetirementSlotTestProfile.on else RetirementSlotTestProfile.off
        val b = Module(new IntegerBackend(params, registerCanonicalStoreEvent = params.registeredCanonicalStoreEvent,
            retirementSlotIdentity = enabled))
        require(b.p == params && b.ledger.p == params && params.retirementSlotIdentity == enabled &&
            b.retirementSlotIdentity == enabled &&
            b.ledger.retirementSlotIdentity == enabled, "actual backend/ledger local switch mismatch")
        b.io.allocate := VecInit(requests)
        b.io.rawDestinations.foreach(_ := VecInit(requests.map(_.bits.rename.rd)))
        b.io.rawRequests.foreach(_ := VecInit(requests.map(_.bits.rename)))
        b.io.fetchFaultMask.foreach(_ := VecInit(requests.map(r => r.bits.fetchFault || r.bits.fetchPageFault)).asUInt)
        b.io.commitEnable := io.commitEnable
        b.io.recover := 0.U.asTypeOf(b.io.recover)
        b.io.inspectRegister := 0.U
        b.io.imsic.get.request.ready := true.B
        b.io.imsic.get.response.valid := false.B
        b.io.imsic.get.response.bits := 0.U.asTypeOf(b.io.imsic.get.response.bits)
        b.io.externalInterrupt.get := false.B
        b.io.supervisorExternalInterrupt.get := false.B
        b.io.timerInterrupt.get := false.B
        b.io.timeValue.get := 0.U
        b.io.emptyPc.get := io.pc
        b.io.fetchQuiescent.get := true.B
        b.io.fenceIFlushReady.get := true.B
        b.io.vmFlushReady.get := true.B
        b.io.externalPrefetchBusy.foreach(_ := false.B)
        b.io.memory.request.ready := io.memoryReady
        b.io.memory.response.valid := io.memoryResponse.valid
        b.io.memory.response.bits := io.memoryResponse.bits
        b.io.loadPrecheck.foreach { port =>
            port.response := 0.U.asTypeOf(port.response)
            port.epoch := 0.U
            port.stable := true.B
        }
        b.io.canonicalStore.foreach(port => port.checked := 0.U.asTypeOf(port.checked))
        b.io.posted.foreach { port =>
            port.contextEpoch := 0.U
            port.externalBusy := false.B
            port.blockNew := false.B
        }
        b
    }
    val off = backends.head
    val on = backends(1)
    def tap[T <: Data](value: T): T = BoringUtils.bore(value)
    def sameValid[T <: Data](a: ValidIO[T], b: ValidIO[T], label: String): Unit = {
        assert(a.valid === b.valid, s"retirement pair $label valid")
        when(a.valid) { assert(a.bits.asUInt === b.bits.asUInt, s"retirement pair $label payload") }
    }
    for (lane <- 0 until 2) {
        sameValid(off.io.renamed(lane), on.io.renamed(lane), s"rename $lane")
        sameValid(off.io.commit(lane), on.io.commit(lane), s"commit $lane")
        sameValid(off.io.issued(lane), on.io.issued(lane), s"issue $lane")
        assert(tap(off.executionStages(lane).io.cancel) === tap(on.executionStages(lane).io.cancel))
        assert(tap(off.executionStages(lane).io.deq.ready) === tap(on.executionStages(lane).io.deq.ready))
        assert(tap(off.executionStages(lane).io.occupied) === tap(on.executionStages(lane).io.occupied))
        assert(tap(off.ledger.io.completionAccepted(lane)) === tap(on.ledger.io.completionAccepted(lane)))
        assert(tap(off.physicalWrites.get(lane).valid) === tap(on.physicalWrites.get(lane).valid))
        when(tap(off.physicalWrites.get(lane).valid)) {
            assert(tap(off.physicalWrites.get(lane).bits).asUInt === tap(on.physicalWrites.get(lane).bits).asUInt)
        }
        when(!tap(on.ledger.recoveryCycle)) {
            assert(tap(off.ledger.io.sameCycleRetire(lane)) === tap(on.ledger.io.sameCycleRetire(lane)))
            assert(tap(off.ledger.retirementAccepted(lane)) === tap(on.ledger.retirementAccepted(lane)))
        }
    }
    assert(tap(off.pendingStoreProof.get.io.bind) === tap(on.pendingStoreProof.get.io.bind))
    assert(tap(off.pendingStoreProof.get.io.bound) === tap(on.pendingStoreProof.get.io.bound))
    assert(tap(off.pendingStoreCredit.get.io.reserved).asUInt === tap(on.pendingStoreCredit.get.io.reserved).asUInt)
    assert(tap(off.pendingStoreCredit.get.io.active).asUInt === tap(on.pendingStoreCredit.get.io.active).asUInt)
    assert(tap(off.pendingStoreCredit.get.io.owner).asUInt === tap(on.pendingStoreCredit.get.io.owner).asUInt)
    sameValid(off.io.headException, on.io.headException, "head exception")
    sameValid(off.io.redirect, on.io.redirect, "redirect")
    sameValid(off.io.trap.get, on.io.trap.get, "trap")
    assert(off.io.memory.request.valid === on.io.memory.request.valid)
    when(off.io.memory.request.valid) {
        assert(off.io.memory.request.bits.asUInt === on.io.memory.request.bits.asUInt)
    }
    assert(off.io.memory.response.ready === on.io.memory.response.ready)
    assert(off.io.occupancy === on.io.occupancy)
    assert(tap(off.pending).asUInt === tap(on.pending).asUInt)
    assert(tap(off.pendingStoreProof.get.io.clearOwners) === tap(on.pendingStoreProof.get.io.clearOwners))
    assert(tap(off.pendingStoreProof.get.io.consume).asUInt === tap(on.pendingStoreProof.get.io.consume).asUInt)
    for ((a, b) <- Seq(
        off.io.pauseFetch.get -> on.io.pauseFetch.get,
        off.io.recoveryAccepted -> on.io.recoveryAccepted,
        off.io.recovering -> on.io.recovering,
        off.io.memoryBusy -> on.io.memoryBusy,
        tap(off.pendingStoreProof.get.io.flushQueries) -> tap(on.pendingStoreProof.get.io.flushQueries),
        tap(off.lsu.io.start.valid) -> tap(on.lsu.io.start.valid),
        tap(off.lsu.io.start.ready) -> tap(on.lsu.io.start.ready))) assert(a === b)
    for ((b, observed) <- backends.zip(Seq(io.reference, io.candidate))) {
        observed.renamed0.valid := b.io.renamed(0).valid
        observed.renamed0.bits := b.io.renamed(0).bits.token
        observed.renamed1.valid := b.io.renamed(1).valid
        observed.renamed1.bits := b.io.renamed(1).bits.token
        observed.issued0 := b.io.issued(0)
        observed.issued1 := b.io.issued(1)
        observed.commit0 := b.io.commit(0)
        observed.commit1 := b.io.commit(1)
        observed.occupancy := b.io.occupancy
        observed.head := tap(b.ledger.head)
        observed.recoveryCycle := tap(b.ledger.recoveryCycle)
        observed.commitEnable := tap(b.ledger.io.commitEnable)
        observed.recovery.valid := tap(b.ledger.io.recoveryAccepted)
        observed.recovery.bits := tap(b.ledger.io.parallelRecovery.get.selected.bits)
        observed.producers := VecInit(Seq(tap(b.lsu.io.complete.valid), tap(b.mulDiv.io.complete.valid),
            tap(b.multiplier.io.complete.valid), tap(b.systemComplete.valid),
            (if (p.precompleteMispredictedBranch) false.B else tap(b.branchRedirectReady)))).asUInt
        observed.execOccupied := VecInit(b.executionStages.map(s => tap(s.io.occupied))).asUInt
        observed.execReady := VecInit(b.executionStages.map(s => tap(s.io.deq.ready))).asUInt
        observed.execCancel := VecInit(b.executionStages.map(s => tap(s.io.cancel))).asUInt
        observed.execBranch := VecInit(b.executingOperands.map(e => tap(e.entry.request.controlFlow) =/= ControlFlow.none)).asUInt
        observed.actual := VecInit(b.ledger.io.complete.map(c => tap(c.valid))).asUInt
        observed.intent := b.ledger.io.retirementIntentValid.map(v => tap(v).asUInt).getOrElse(observed.actual)
        observed.retireClass := tap(b.ledger.io.sameCycleRetire).asUInt
        observed.retireFault := tap(b.ledger.io.sameCycleFault.get).asUInt
        observed.qualified := tap(b.ledger.retirementAccepted).asUInt
        observed.completion0 := tap(b.ledger.io.complete(0).bits)
        observed.completion1 := tap(b.ledger.io.complete(1).bits)
        observed.trap := b.io.trap.get.valid
        observed.physicalWriteMask := VecInit(b.physicalWrites.get.map(w => tap(w.valid))).asUInt
    }
    io.memoryRequest.valid := off.io.memory.request.valid
    io.memoryRequest.bits := off.io.memory.request.bits
    io.memoryResponseReady := off.io.memory.response.ready
}
