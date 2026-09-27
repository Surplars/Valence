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
    backend.io.complete(0)     := io.complete0
    backend.io.complete(1)     := io.complete1
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
        moveAlias = args.lift(5).contains("move-alias")
    )
    ChiselStage.emitCHIRRTLFile(new RenameRobGsim(p), Array("--target-dir", target))
}
