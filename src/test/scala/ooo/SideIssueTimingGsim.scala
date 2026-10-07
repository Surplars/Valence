package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Small independent owner-readiness and late-grant contract fixture. */
class SideIssueTimingGsim extends Module {
    val p = OooParams(robEntries = 16, physicalRegs = 48)
    val io = IO(new Bundle {
        val physical = Input(UInt(64.W))
        val active = Input(UInt(16.W))
        val source1 = Input(new OperandScalarPorts(8, 16))
        val source2 = Input(new OperandScalarPorts(8, 16))
        val allocate0 = Input(Valid(new OwnerOperandAllocation(p)))
        val allocate1 = Input(Valid(new OwnerOperandAllocation(p)))
        val wake0 = Input(Valid(UInt(6.W)))
        val wake1 = Input(Valid(UInt(6.W)))
        val wake2 = Input(Valid(UInt(6.W)))
        val reserve0 = Input(Valid(UInt(6.W)))
        val reserve1 = Input(Valid(UInt(6.W)))
        val head = Input(UInt(4.W))
        val stores = Input(UInt(16.W))
        val others = Input(UInt(16.W))
        val multiply = Input(UInt(16.W))
        val divide = Input(UInt(16.W))
        val multiplyReady = Input(Bool())
        val divideReady = Input(Bool())
        // Independent combinational candidate domain; held across four late-credit
        // perturbations by the C++ oracle, unrelated to readiness-state updates.
        val candidateFlags = Input(new OperandScalarPorts(16, 16))
        val candidateReady1 = Input(UInt(16.W))
        val candidateReady2 = Input(UInt(16.W))
        val candidateHead = Input(UInt(4.W))
        val candidateBranchRedirect = Input(Bool())
        val aluPromise1 = Input(UInt(16.W))
        val aluPromise2 = Input(UInt(16.W))
        val executionOccupied = Input(Bool())
        val executionForwardable = Input(Bool())
        val executionDeqReady = Input(Bool())
        val multiplyFinish = Input(Bool())
        val candidateEligible = Output(UInt(16.W))
        val candidate0 = Output(UInt(16.W))
        val candidate1 = Output(UInt(16.W))
        val legacyStoreEligible = Output(UInt(16.W))
        val legacyAluEligible = Output(UInt(16.W))
        val candidateShared0 = Output(UInt(16.W))
        val candidateShared1 = Output(UInt(16.W))
        val ready1 = Output(UInt(16.W))
        val ready2 = Output(UInt(16.W))
        val store0 = Output(UInt(16.W))
        val store1 = Output(UInt(16.W))
        val shared0 = Output(UInt(16.W))
        val shared1 = Output(UInt(16.W))
        val multiplyOwner = Output(UInt(16.W))
        val divideOwner = Output(UInt(16.W))
        val multiplyGrant = Output(Bool())
        val divideGrant = Output(Bool())
        val selectedValid = Output(Bool())
        val selectedIndex = Output(UInt(4.W))
    })
    val readiness = Module(new OwnerOperandReady(p))
    readiness.io.physical := io.physical(47, 0)
    readiness.io.active := io.active
    readiness.io.source1 := VecInit((0 until 16).map(i => io.source1.at(i)(5, 0)))
    readiness.io.source2 := VecInit((0 until 16).map(i => io.source2.at(i)(5, 0)))
    readiness.io.allocate := VecInit(Seq(io.allocate0, io.allocate1))
    readiness.io.wake := VecInit(Seq(io.wake0, io.wake1, io.wake2))
    readiness.io.reserve := VecInit(Seq(io.reserve0, io.reserve1))
    io.ready1 := readiness.io.ready1.asUInt
    io.ready2 := readiness.io.ready2.asUInt
    val storeSelection = Module(new CircularIssueSelector(p, parallelRanks = true))
    storeSelection.io.eligible := io.stores
    storeSelection.io.head := io.head
    io.store0 := storeSelection.io.first
    io.store1 := storeSelection.io.second
    val sharedSelection = Module(new CircularIssueSelector(p, parallelRanks = true))
    sharedSelection.io.eligible := io.stores | io.others
    sharedSelection.io.head := io.head
    io.shared0 := sharedSelection.io.first
    io.shared1 := sharedSelection.io.second
    val selection = Module(new SplitMulDivSelector(p))
    selection.io.eligible := VecInit(Seq(io.multiply, io.divide))
    selection.io.head := io.head
    selection.io.available := VecInit(Seq(io.multiplyReady, io.divideReady))
    io.multiplyOwner := selection.io.owner(0)
    io.divideOwner := selection.io.owner(1)
    io.multiplyGrant := selection.io.grant(0)
    io.divideGrant := selection.io.grant(1)
    io.selectedValid := selection.io.selectedValid
    io.selectedIndex := selection.io.selectedIndex
    val candidates = Module(new StorePreparationEligibility(p))
    candidates.io.head := io.candidateHead
    candidates.io.branchRedirect := io.candidateBranchRedirect
    val generic = Wire(Vec(16, Bool()))
    val filtered = Wire(Vec(16, Bool()))
    val genericAlu = Wire(Vec(16, Bool()))
    // A deliberately late ALU promise, just as completion credit gates dequeue
    // in the backend. It is NOT connected to StorePreparationEligibility.
    val aluWake = io.executionOccupied && io.executionForwardable &&
        io.executionDeqReady && !io.multiplyFinish
    for (slot <- 0 until 16) {
        val flags = io.candidateFlags.at(slot)
        val entry = candidates.io.entries(slot)
        entry.pending := flags(0)
        entry.system := flags(1)
        entry.mulDiv := flags(2)
        entry.memory := flags(3)
        entry.store := flags(4)
        entry.prepared := flags(5)
        entry.addressKnown := flags(6)
        entry.usePc := flags(7)
        entry.useImmediate := flags(8)
        entry.controlFlow := flags(9)
        entry.operandReady1 := io.candidateReady1(slot)
        entry.operandReady2 := io.candidateReady2(slot)
        val prepareStore = entry.memory && entry.store && !entry.prepared && slot.U =/= io.candidateHead
        val firstReady = entry.usePc || Mux(entry.memory, entry.operandReady1,
            entry.operandReady1 || (aluWake && io.aluPromise1(slot)))
        val secondReady = entry.useImmediate || Mux(entry.memory, entry.operandReady2,
            entry.operandReady2 || (aluWake && io.aluPromise2(slot)))
        generic(slot) := entry.pending && !entry.system && !entry.mulDiv &&
            (!entry.memory || prepareStore) && firstReady &&
            (secondReady || (prepareStore && !entry.addressKnown)) &&
            (!io.candidateBranchRedirect || !entry.controlFlow)
        filtered(slot) := generic(slot) && entry.memory && entry.store
        genericAlu(slot) := generic(slot) && !entry.memory
    }
    io.candidateEligible := candidates.io.eligible
    io.legacyStoreEligible := filtered.asUInt
    io.legacyAluEligible := genericAlu.asUInt
    val candidateSelection = Module(new CircularIssueSelector(p, parallelRanks = true))
    candidateSelection.io.head := io.candidateHead
    candidateSelection.io.eligible := candidates.io.eligible
    io.candidate0 := candidateSelection.io.first
    io.candidate1 := candidateSelection.io.second
    val candidateShared = Module(new CircularIssueSelector(p, parallelRanks = true))
    candidateShared.io.head := io.candidateHead
    candidateShared.io.eligible := generic.asUInt
    io.candidateShared0 := candidateShared.io.first
    io.candidateShared1 := candidateShared.io.second
}

object SideIssueTimingGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new SideIssueTimingGsim, Array("--target-dir", args.head))
}
