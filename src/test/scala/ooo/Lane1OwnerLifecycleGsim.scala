package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class Lane1OwnerLifecycleObservation extends Bundle {
    val ownerMatch = Bool()
    val rowKnown = Bool()
    val occupied = Bool()
    val dequeueValid = Bool()
    val enqueueReady = Bool()
    val cancel = Bool()
    val slotIndex = UInt(4.W)
    val slotTag = UInt(64.W)
    val renamed = UInt(2.W)
    val renameIndex0 = UInt(4.W)
    val renameIndex1 = UInt(4.W)
    val renameTag0 = UInt(64.W)
    val renameTag1 = UInt(64.W)
    val accepted = UInt(2.W)
    val committed = UInt(2.W)
    val commitIndex0 = UInt(4.W)
    val commitIndex1 = UInt(4.W)
    val commitTag0 = UInt(64.W)
    val commitTag1 = UInt(64.W)
    val commitData0 = UInt(64.W)
    val commitData1 = UInt(64.W)
    val occupancy = UInt(5.W)
    val recovering = Bool()
    val recoveryAccepted = Bool()
    val headException = Bool()
    val exceptionTag = UInt(64.W)
    val exceptionCause = UInt(64.W)
    val exceptionTval = UInt(64.W)
    val mutationApplied = Bool()
}

/** Paired real ledgers and one real registered execution slot per ledger.
  * Rows are written ONLY by accepted rename tokens; arbitrary/stale/high-bit
  * captures enter through the ordinary stage input, never by seeding ROB state.
  * Nonwriting allocations deliberately keep this owner-lifecycle fixture small.
  */
class Lane1OwnerLifecycleGsim extends Module {
    val base = OooParams(robEntries = 16, physicalRegs = 40, recoveryWidth = 4,
        registeredBranchRedirect = true, registeredRobRetirement = true,
        precompleteMispredictedBranch = true, earlyRankedOperands = true,
        registeredIssueExecute = true, parallelIssuePayload = true)
    val io = IO(new Bundle {
        val allocate = Input(UInt(2.W))
        val dispatchReady = Input(Bool())
        val commitEnable = Input(Bool())
        val sameCycleRetire = Input(UInt(2.W))
        val complete0 = Input(Valid(new BackendCompletion(base)))
        val complete1Enable = Input(Bool())
        val complete1Data = Input(UInt(64.W))
        val complete1Fault = Input(Bool())
        val complete1Cause = Input(UInt(64.W))
        val complete1Tval = Input(UInt(64.W))
        val captureValid = Input(Bool())
        val captureFromRename = Input(Bool())
        val captureRenameLane = Input(Bool())
        val captureIndex = Input(UInt(4.W))
        val captureTag = Input(UInt(64.W))
        val dequeueReady = Input(Bool())
        val kill = Input(Bool())
        val recover = Input(Valid(new RecoveryRequest(base)))
        // Test-only, exercised faults: 1=truncate tag, 2=valid-qualified equality,
        // 3=unmasked stale cancellation. Zero is the unmodified candidate.
        val mutation = Input(UInt(2.W))
        val legacy = Output(new Lane1OwnerLifecycleObservation)
        val shared = Output(new Lane1OwnerLifecycleObservation)
    })
    for ((enabled, observation) <- Seq(false -> io.legacy, true -> io.shared)) {
        val p = base.copy(sharedLane1OwnerMatch = enabled)
        val rob = Module(new RenameRob(p))
        val stage = Module(new IssueExecuteStage(68))
        val rows = Reg(Vec(16, new RobToken(p)))
        val known = RegInit(VecInit(Seq.fill(16)(false.B)))
        for (lane <- 0 until 2) {
            rob.io.allocate(lane) := 0.U.asTypeOf(Valid(new RenameRequest))
            rob.io.allocate(lane).valid := io.allocate(lane)
            rob.io.allocate(lane).bits.instruction := "h00000013".U
            rob.io.sameCycleRetire(lane) := io.sameCycleRetire(lane)
            when(rob.io.renamed(lane).valid) {
                val index = rob.io.renamed(lane).bits.token.index
                rows(index) := rob.io.renamed(lane).bits.token
                known(index) := true.B
            }
        }
        rob.io.dispatchReady := io.dispatchReady
        rob.io.commitEnable := io.commitEnable
        rob.io.fastHeadRetire := 0.U.asTypeOf(Valid(new BackendCompletion(p)))
        rob.io.recover := io.recover
        rob.io.recoveryProbe := io.recover
        rob.io.inspectRegister := 0.U
        rob.io.complete(0) := io.complete0
        val token = stage.io.deq.bits.asTypeOf(new RobToken(p))
        rob.io.complete(1) := 0.U.asTypeOf(Valid(new BackendCompletion(p)))
        rob.io.complete(1).valid := io.complete1Enable && stage.io.deq.fire
        // The query must always see the raw registered payload, even when idle.
        rob.io.complete(1).bits.token := token
        rob.io.complete(1).bits.data := io.complete1Data
        rob.io.complete(1).bits.nextPc := io.complete1Data + 4.U
        rob.io.complete(1).bits.exception := io.complete1Fault
        rob.io.complete(1).bits.cause := io.complete1Cause
        rob.io.complete(1).bits.tval := io.complete1Tval
        // Match the production legacy queue address exactly. Its idle result
        // is nonfunctional; only the shared ROB query promises raw-token lookup.
        val ownerIndex = Mux(stage.io.occupied, token.index, 0.U)
        val queueMatch = rows(ownerIndex).asUInt === token.asUInt
        val pureMatch = if (enabled) rob.io.lane1OwnerMatch.get else queueMatch
        val usedMatch = if (enabled) MuxLookup(io.mutation, pureMatch)(Seq(
            1.U -> (rows(token.index).tag(31, 0) === token.tag(31, 0)),
            2.U -> (pureMatch && io.complete1Enable))) else pureMatch
        val baselineCancellation = stage.io.occupied && (!pureMatch || io.kill)
        val cancellation = if (enabled)
            Mux(io.mutation === 3.U && known(token.index) && !stage.io.occupied && !pureMatch,
                true.B, stage.io.occupied && (!usedMatch || io.kill))
        else baselineCancellation
        stage.io.cancel := cancellation
        stage.io.deq.ready := io.dequeueReady
        val renamed = rob.io.renamed(io.captureRenameLane)
        val supplied = Wire(new RobToken(p))
        supplied.index := io.captureIndex
        supplied.tag := io.captureTag
        stage.io.enq.bits := Mux(io.captureFromRename, renamed.bits.token, supplied).asUInt
        stage.io.enq.valid := io.captureValid && (!io.captureFromRename || renamed.valid)
        observation.ownerMatch := usedMatch
        observation.rowKnown := known(token.index)
        observation.occupied := stage.io.occupied
        observation.dequeueValid := stage.io.deq.valid
        observation.enqueueReady := stage.io.enq.ready
        observation.cancel := cancellation
        observation.slotIndex := token.index
        observation.slotTag := token.tag
        observation.renamed := VecInit(rob.io.renamed.map(_.valid)).asUInt
        observation.renameIndex0 := rob.io.renamed(0).bits.token.index
        observation.renameIndex1 := rob.io.renamed(1).bits.token.index
        observation.renameTag0 := rob.io.renamed(0).bits.token.tag
        observation.renameTag1 := rob.io.renamed(1).bits.token.tag
        observation.accepted := rob.io.completionAccepted.asUInt
        observation.committed := VecInit(rob.io.commit.map(_.valid)).asUInt
        observation.commitIndex0 := rob.io.commit(0).bits.token.index
        observation.commitIndex1 := rob.io.commit(1).bits.token.index
        observation.commitTag0 := rob.io.commit(0).bits.token.tag
        observation.commitTag1 := rob.io.commit(1).bits.token.tag
        observation.commitData0 := rob.io.commit(0).bits.data
        observation.commitData1 := rob.io.commit(1).bits.data
        observation.occupancy := rob.io.occupancy
        observation.recovering := rob.io.recovering
        observation.recoveryAccepted := rob.io.recoveryAccepted
        observation.headException := rob.io.headException.valid
        observation.exceptionTag := rob.io.headException.bits.token.tag
        observation.exceptionCause := rob.io.headException.bits.cause
        observation.exceptionTval := rob.io.headException.bits.tval
        observation.mutationApplied := (if (enabled) known(token.index) &&
            ((usedMatch =/= pureMatch) || (cancellation =/= baselineCancellation)) else false.B)
    }
}

object Lane1OwnerLifecycleGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new Lane1OwnerLifecycleGsim, Array("--target-dir", args.head))
}
