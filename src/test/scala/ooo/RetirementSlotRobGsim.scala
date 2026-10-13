package soc.core.ooo

import chisel3._
import chisel3.util._

/** Public-input ledger fixture. Requests are nonwriting so the independent
  * oracle can concentrate on full owner identity, completion, ordered retirement
  * and both rollback candidates without fabricating any internal ROB state.
  */
class RetirementSlotRobInput(p: OooParams) extends Bundle {
    val allocate0 = Valid(new RenameRequest)
    val allocate1 = Valid(new RenameRequest)
    val complete0 = Valid(new BackendCompletion(p))
    val complete1 = Valid(new BackendCompletion(p))
    val intent = UInt(2.W)
    val sameCycleRetire = UInt(2.W)
    val dispatchReady = Bool()
    val commitEnable = Bool()
    val external = Valid(new RecoveryRequest(p))
    val local = Valid(new RecoveryRequest(p))
    val headTrap = Bool()
    val headSystem = Bool()
    val loadOrderLimit = Valid(new RobToken(p))
}

class RetirementSlotRobObservation(p: OooParams) extends Bundle {
    val renamed0 = Valid(new RenamedInstruction(p))
    val renamed1 = Valid(new RenamedInstruction(p))
    val commit0 = Valid(new CommitRecord(p))
    val commit1 = Valid(new CommitRecord(p))
    val completionAccepted0 = Bool()
    val completionAccepted1 = Bool()
    val externalAccepted = Bool()
    val externalWins = Bool()
    val selected = Valid(new RecoveryRequest(p))
    val killed = UInt(p.robEntries.W)
    val recoveryAccepted = Bool()
    val headTrapAccepted = Bool()
    val headSystemAccepted = Bool()
    val headSystemToken = new RobToken(p)
    val recovering = Bool()
    val occupancy = UInt(p.countBits.W)
    val headValid = Bool()
    val headDone = Bool()
    val headPc = UInt(64.W)
    val headException = Valid(new HeadException(p))
    val freeCount = UInt(log2Ceil(p.physicalRegs + 1).W)
    val tagExhausted = Bool()
}

class RetirementSlotRobPort(p: OooParams) extends Bundle {
    val in = Input(new RetirementSlotRobInput(p))
    val reference = Output(new RetirementSlotRobObservation(p))
    val candidate = Output(new RetirementSlotRobObservation(p))
}

class RetirementSlotRobGsim extends Module {
    val baseline = RetirementSlotTestProfile.off
    val candidate = RetirementSlotTestProfile.on
    require(candidate.copy(retirementSlotIdentity = false) == baseline && !baseline.retirementSlotIdentity &&
        candidate.retirementSlotIdentity, "ROB pair may differ only in the unified retirement-slot flag")
    require(baseline.renameWidth == 2 && baseline.completionWidth == 2 && baseline.commitWidth == 2)
    require(baseline.robEntries == 16 && baseline.tagBits == 64 && baseline.recoveryWidth == 4)
    require(baseline.physicalRegs == 48 && baseline.registeredRobRetirement)
    require(baseline.parallelRecoveryAdmission && baseline.fastHeadTrapRecovery && baseline.fastHeadSystemRecovery)
    val io = IO(new RetirementSlotRobPort(baseline))

    for ((p, out, enabled) <- Seq((baseline, io.reference, false), (candidate, io.candidate, true))) {
        val ledger = Module(new RenameRob(p, retirementSlotIdentity = enabled))
        require(ledger.p == p && p.retirementSlotIdentity == enabled && ledger.retirementSlotIdentity == enabled)
        ledger.io.allocate(0) := io.in.allocate0
        ledger.io.allocate(1) := io.in.allocate1
        ledger.io.rawRequests.foreach { raw =>
            raw(0) := io.in.allocate0.bits
            raw(1) := io.in.allocate1.bits
        }
        ledger.io.rawDestinations.foreach { rd =>
            rd(0) := io.in.allocate0.bits.rd
            rd(1) := io.in.allocate1.bits.rd
        }
        ledger.io.fetchFaultMask.foreach(_ := 0.U)
        ledger.io.complete(0) := io.in.complete0
        ledger.io.complete(1) := io.in.complete1
        ledger.io.retirementIntentValid.foreach { intents =>
            intents(0) := io.in.intent(0)
            intents(1) := io.in.intent(1)
        }
        ledger.io.sameCycleRetire := VecInit((0 until 2).map(io.in.sameCycleRetire(_)))
        ledger.io.sameCycleFault.foreach { faults =>
            faults(0) := io.in.complete0.bits.exception
            faults(1) := io.in.complete1.bits.exception
        }
        ledger.io.fastHeadRetire := 0.U.asTypeOf(Valid(new BackendCompletion(p)))
        ledger.io.loadOrderRetireLimit.foreach(_ := io.in.loadOrderLimit)
        ledger.io.dispatchReady := io.in.dispatchReady
        ledger.io.commitEnable := io.in.commitEnable
        ledger.io.recover := io.in.external
        ledger.io.recoveryProbe := io.in.external
        ledger.io.parallelRecovery.get.local := io.in.local
        ledger.io.headTrap.get.valid := io.in.headTrap
        ledger.io.headSystem.get.valid := io.in.headSystem
        ledger.io.inspectRegister := 0.U

        out.renamed0 := ledger.io.renamed(0)
        out.renamed1 := ledger.io.renamed(1)
        out.commit0 := ledger.io.commit(0)
        out.commit1 := ledger.io.commit(1)
        out.completionAccepted0 := ledger.io.completionAccepted(0)
        out.completionAccepted1 := ledger.io.completionAccepted(1)
        out.externalAccepted := ledger.io.recoveryProbeAccepted
        out.externalWins := ledger.io.parallelRecovery.get.externalWins
        out.selected := ledger.io.parallelRecovery.get.selected
        out.killed := ledger.io.parallelRecovery.get.killed
        out.recoveryAccepted := ledger.io.recoveryAccepted
        out.headTrapAccepted := ledger.io.headTrap.get.accepted
        out.headSystemAccepted := ledger.io.headSystem.get.accepted
        out.headSystemToken := ledger.io.headSystem.get.headToken
        out.recovering := ledger.io.recovering
        out.occupancy := ledger.io.occupancy
        out.headValid := ledger.io.headValid
        out.headDone := ledger.io.headDone
        out.headPc := ledger.io.headPc
        out.headException := ledger.io.headException
        out.freeCount := ledger.io.freeCount
        out.tagExhausted := ledger.io.tagExhausted
    }
}
