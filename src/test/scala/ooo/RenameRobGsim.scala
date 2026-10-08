package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Scalar lane names work around GSIM's scalar-only generated top-level accessor API. */
class RenameRobGsim(p: OooParams) extends Module {
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)
    val io = IO(new Bundle {
        val allocate0           = Input(Valid(new RenameRequest))
        val allocate1           = Input(Valid(new RenameRequest))
        val complete0           = Input(Valid(new BackendCompletion(p)))
        val complete1           = Input(Valid(new BackendCompletion(p)))
        val renamed0            = Output(Valid(new RenamedInstruction(p)))
        val renamed1            = Output(Valid(new RenamedInstruction(p)))
        val commit0             = Output(Valid(new CommitRecord(p)))
        val commit1             = Output(Valid(new CommitRecord(p)))
        val completionAccepted0 = Output(Bool())
        val completionAccepted1 = Output(Bool())
        val dispatchReady       = Input(Bool())
        val commitEnable        = Input(Bool())
        val recover             = Input(Valid(new RecoveryRequest(p)))
        val headTrap = if (p.fastHeadTrapRecovery) Some(Input(Bool())) else None
        val headTrapAccepted = if (p.fastHeadTrapRecovery) Some(Output(Bool())) else None
        val headSystem = if (p.fastHeadSystemRecovery) Some(Input(Bool())) else None
        val headSystemAccepted = if (p.fastHeadSystemRecovery) Some(Output(Bool())) else None
        val headSystemToken = if (p.fastHeadSystemRecovery) Some(Output(new RobToken(p))) else None
        val recoveryAccepted    = Output(Bool())
        val recovering          = Output(Bool())
        val occupancy           = Output(UInt(p.countBits.W))
        val freeCount           = Output(UInt(log2Ceil(p.physicalRegs + 1).W))
        val tagExhausted        = Output(Bool())
        val headException       = Output(Valid(new HeadException(p)))
        val inspectRegister     = Input(UInt(5.W))
        val speculativeMapping  = Output(UInt(p.physBits.W))
        val committedMapping    = Output(UInt(p.physBits.W))
    })
    val backend = Module(new RenameRob(p))
    backend.io.fastHeadRetire := 0.U.asTypeOf(Valid(new BackendCompletion(p)))
    backend.io.allocate(0)     := io.allocate0
    backend.io.allocate(1)     := io.allocate1
    backend.io.rawRequests.foreach { raw =>
        raw(0) := io.allocate0.bits
        raw(1) := io.allocate1.bits
    }
    backend.io.fetchFaultMask.foreach(_ := 0.U)
    backend.io.rawDestinations.foreach { indices =>
        // Non-writers deliberately carry unrelated raw indices; they must never
        // allocate or mutate the RAT. The independent ledger oracle is unchanged.
        indices(0) := Mux(io.allocate0.bits.writesRd, io.allocate0.bits.rd, (io.allocate0.bits.rd + 17.U)(4, 0))
        indices(1) := Mux(io.allocate1.bits.writesRd, io.allocate1.bits.rd, (io.allocate1.bits.rd + 9.U)(4, 0))
    }
    backend.io.complete(0)     := io.complete0
    backend.io.complete(1)     := io.complete1
    backend.io.sameCycleRetire.foreach(_ := true.B)
    backend.io.sameCycleFault.foreach { faults =>
        faults(0) := io.complete0.bits.exception
        faults(1) := io.complete1.bits.exception
    }
    io.renamed0                := backend.io.renamed(0)
    io.renamed1                := backend.io.renamed(1)
    io.commit0                 := backend.io.commit(0)
    io.commit1                 := backend.io.commit(1)
    io.completionAccepted0     := backend.io.completionAccepted(0)
    io.completionAccepted1     := backend.io.completionAccepted(1)
    backend.io.dispatchReady   := io.dispatchReady
    backend.io.commitEnable    := io.commitEnable
    backend.io.recover         := io.recover
    backend.io.recoveryProbe   := io.recover
    backend.io.headTrap.foreach { port =>
        port.valid := io.headTrap.get
        io.headTrapAccepted.get := port.accepted
    }
    backend.io.headSystem.foreach { port =>
        port.valid := io.headSystem.get
        io.headSystemAccepted.get := port.accepted
        io.headSystemToken.get := port.headToken
    }
    backend.io.parallelRecovery.foreach(_.local := 0.U.asTypeOf(Valid(new RecoveryRequest(p))))
    backend.io.inspectRegister := io.inspectRegister
    io.recoveryAccepted        := backend.io.recoveryAccepted
    io.recovering              := backend.io.recovering
    io.occupancy               := backend.io.occupancy
    io.freeCount               := backend.io.freeCount
    io.tagExhausted            := backend.io.tagExhausted
    io.headException           := backend.io.headException
    io.speculativeMapping      := backend.io.speculativeMapping
    io.committedMapping        := backend.io.committedMapping
}

object RenameRobGsimMain extends App {
    val target = args.headOption.getOrElse("build/gsim/backend")
    val p      = OooParams(
        robEntries = args.lift(1).map(_.toInt).getOrElse(32),
        physicalRegs = args.lift(2).map(_.toInt).getOrElse(64),
        tagBits = args.lift(3).map(_.toInt).getOrElse(64),
        recoveryWidth = args.lift(4).map(_.toInt).getOrElse(1),
        compressedInstructions = args.lift(5).contains("move-alias"),
        moveAlias = args.lift(5).contains("move-alias"),
        parallelRenameAdmission = args.drop(5).contains("early-destinations"),
        earlyRenameDestinations = args.drop(5).contains("early-destinations"),
        parallelRenameRanks = args.drop(5).contains("parallel-ranks"),
        parallelArchitecturalDestinations = args.drop(5).contains("early-architectural-destinations"),
        registeredBranchRedirect = args.drop(5).contains("separate-retire-fault"),
        registeredRobRetirement = args.drop(5).contains("separate-retire-fault"),
        separateBranchRetireFault = args.drop(5).contains("separate-retire-fault"),
        parallelRecoveryAdmission = args.drop(5).contains("parallel-recovery-admission") ||
            args.drop(5).contains("fast-head-trap") || args.drop(5).contains("fast-head-system"),
        fastHeadTrapRecovery = args.drop(5).contains("fast-head-trap"),
        fastHeadSystemRecovery = args.drop(5).contains("fast-head-system"),
        tentativeRenameSources = args.drop(5).contains("tentative-sources"),
        bankedRobPayload = args.drop(5).contains("banked-payload")
    )
    ChiselStage.emitCHIRRTLFile(new RenameRobGsim(p), Array("--target-dir", target))
}
