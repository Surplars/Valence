package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Test-only raw/fault boundary plus actual ledger and allocation-ready state.
  * External wake inputs are already-authorized physical events, not IRQ/NEMU
  * witnesses. No completion/commit/recovery occurs; each directed case resets.
  */
class RenameFaultCandidatesGsim(p: OooParams) extends Module {
    require(p.robEntries == 16 && p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)
    require(p.tentativeRenameSources && p.moveAlias && p.compressedInstructions)
    val io = IO(new Bundle {
        val raw0 = Input(Valid(new RenameRequest))
        val raw1 = Input(Valid(new RenameRequest))
        val faultMask = Input(UInt(2.W))
        val dispatchReady = Input(Bool())
        val physical = Input(UInt(p.physicalRegs.W))
        val wake0 = Input(Valid(UInt(p.physBits.W)))
        val wake1 = Input(Valid(UInt(p.physBits.W)))
        val wake2 = Input(Valid(UInt(p.physBits.W)))
        val renamed0 = Output(Valid(new RenamedInstruction(p)))
        val renamed1 = Output(Valid(new RenamedInstruction(p)))
        val freeCount = Output(UInt(log2Ceil(p.physicalRegs + 1).W))
        val occupancy = Output(UInt(p.countBits.W))
        val ownerReady1 = Output(UInt(p.robEntries.W))
        val ownerReady2 = Output(UInt(p.robEntries.W))
        val inspectRegister = Input(UInt(5.W))
        val speculativeMapping = Output(UInt(p.physBits.W))
    })
    val ledger = Module(new RenameRob(p))
    val raw = Wire(Vec(2, Valid(new RenameRequest)))
    raw(0) := io.raw0
    raw(1) := io.raw1
    for (lane <- 0 until 2) {
        val fault = WireDefault(0.U.asTypeOf(new RenameRequest))
        fault.pc := raw(lane).bits.pc
        fault.instruction := raw(lane).bits.instruction
        ledger.io.allocate(lane).valid := raw(lane).valid
        ledger.io.allocate(lane).bits := Mux(io.faultMask(lane), fault, raw(lane).bits)
        ledger.io.rawRequests.get(lane) := raw(lane).bits
        ledger.io.rawDestinations.foreach(indices => indices(lane) := raw(lane).bits.rd)
    }
    ledger.io.fetchFaultMask.get := io.faultMask
    ledger.io.dispatchReady := io.dispatchReady
    ledger.io.commitEnable := false.B
    ledger.io.fastHeadRetire := 0.U.asTypeOf(Valid(new BackendCompletion(p)))
    for (lane <- 0 until p.completionWidth) {
        ledger.io.complete(lane) := 0.U.asTypeOf(Valid(new BackendCompletion(p)))
        ledger.io.sameCycleRetire(lane) := false.B
        ledger.io.sameCycleFault.foreach(faults => faults(lane) := false.B)
    }
    ledger.io.recover := 0.U.asTypeOf(Valid(new RecoveryRequest(p)))
    ledger.io.recoveryProbe := 0.U.asTypeOf(Valid(new RecoveryRequest(p)))
    ledger.io.parallelRecovery.foreach(_.local := 0.U.asTypeOf(Valid(new RecoveryRequest(p))))
    ledger.io.headTrap.foreach(_.valid := false.B)
    ledger.io.headSystem.foreach(_.valid := false.B)
    ledger.io.inspectRegister := io.inspectRegister
    io.renamed0 := ledger.io.renamed(0)
    io.renamed1 := ledger.io.renamed(1)
    io.freeCount := ledger.io.freeCount
    io.occupancy := ledger.io.occupancy
    io.speculativeMapping := ledger.io.speculativeMapping

    val wake = Wire(Vec(p.completionWidth + 1, Valid(UInt(p.physBits.W))))
    wake(0) := io.wake0
    wake(1) := io.wake1
    wake(2) := io.wake2
    val reserve = Wire(Vec(2, Valid(UInt(p.physBits.W))))
    val active = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val sources1 = RegInit(VecInit(Seq.fill(p.robEntries)(0.U(p.physBits.W))))
    val sources2 = RegInit(VecInit(Seq.fill(p.robEntries)(0.U(p.physBits.W))))
    val mirror = Module(new OwnerOperandReady(p, precomputedAllocationReady = true))
    val initialization = Module(new FaultAwareAllocationReady(p))
    initialization.io.sources := ledger.io.sourceCandidates.get
    initialization.io.faults := io.faultMask
    initialization.io.physical := io.physical
    initialization.io.wake := wake
    initialization.io.reserve := reserve
    mirror.io.physical := io.physical
    mirror.io.active := active.asUInt
    mirror.io.wake := wake
    mirror.io.reserve := reserve
    mirror.io.allocationReady1.get := initialization.io.ready1
    mirror.io.allocationReady2.get := initialization.io.ready2
    for (slot <- 0 until p.robEntries) {
        mirror.io.source1(slot) := sources1(slot)
        mirror.io.source2(slot) := sources2(slot)
    }
    for (lane <- 0 until 2) {
        val renamed = ledger.io.renamed(lane)
        reserve(lane).valid := renamed.valid && renamed.bits.writesRd && !renamed.bits.moveAlias
        reserve(lane).bits := renamed.bits.destination
        mirror.io.allocate(lane).valid := renamed.valid
        mirror.io.allocate(lane).bits.index := renamed.bits.token.index
        mirror.io.allocate(lane).bits.source1 := renamed.bits.source1
        mirror.io.allocate(lane).bits.source2 := renamed.bits.source2
        for (slot <- 0 until p.robEntries) {
            when(renamed.valid && renamed.bits.token.index === slot.U) {
                active(slot) := true.B
                sources1(slot) := renamed.bits.source1
                sources2(slot) := renamed.bits.source2
            }
        }
    }
    io.ownerReady1 := mirror.io.ready1.asUInt
    io.ownerReady2 := mirror.io.ready2.asUInt
}

object RenameFaultCandidatesGsimMain extends App {
    val target = args.headOption.getOrElse("build/gsim/rename-fault-candidates")
    val registers = args.lift(1).map(_.toInt).getOrElse(40)
    require(Set(40, 48).contains(registers), "raw-fault short fixture covers PRF40 pressure and PRF48 production geometry")
    val p = OooParams(robEntries = 16, physicalRegs = registers, tagBits = 64,
        compressedInstructions = true, moveAlias = true, tentativeRenameSources = true,
        // Legacy early-destination/rank interfaces forbid aliases. The new raw
        // scalar candidate path supports them independently; do not relax that
        // historical guard just to construct a test fixture.
        parallelRenameAdmission = true, parallelPrfReadyUpdates = true, ownerLocalOperandReady = true)
    println(s"RAW_FAULT_RENAME_FIXTURE rob=16 prf=$registers tag=64 rename=2 moveAlias=true " +
        "rawDecode=true faultMask=true precomputedReady=true oracle=IndependentModel")
    ChiselStage.emitCHIRRTLFile(new RenameFaultCandidatesGsim(p), Array("--target-dir", target))
}
