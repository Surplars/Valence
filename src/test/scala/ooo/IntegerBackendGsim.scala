package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Scalar test ports for the pinned GSIM accessor API. */
class IntegerBackendGsim(p: OooParams) extends Module {
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)
    require(p.memoryEntries == 4, "GSIM harness checks four memory slots")
    val io = IO(new Bundle {
        val allocate0        = Input(Valid(new IntegerRequest))
        val allocate1        = Input(Valid(new IntegerRequest))
        val renamed0         = Output(Valid(new RenamedInstruction(p)))
        val renamed1         = Output(Valid(new RenamedInstruction(p)))
        val commit0          = Output(Valid(new CommitRecord(p)))
        val commit1          = Output(Valid(new CommitRecord(p)))
        val issued0          = Output(Valid(new BackendCompletion(p)))
        val issued1          = Output(Valid(new BackendCompletion(p)))
        val commitEnable     = Input(Bool())
        val recover          = Input(Valid(new RecoveryRequest(p)))
        val recoveryAccepted = Output(Bool())
        val recovering       = Output(Bool())
        val occupancy        = Output(UInt(p.countBits.W))
        val headException    = Output(Valid(new HeadException(p)))
        val inspectRegister  = Input(UInt(5.W))
        val committedValue   = Output(UInt(64.W))
        val redirect         = Output(Valid(new FrontendRedirect(p)))
        val memory           = new DataPort
        val memoryBusy       = Output(Bool())
        val issueCount       = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val memoryDiscarded  = Output(Bool())
        val memoryForwarded  = Output(Bool())
    })
    val backend = Module(new IntegerBackend(p))
    io.memory <> backend.io.memory
    io.memoryBusy              := backend.io.memoryBusy
    io.issueCount              := backend.io.issueCount
    io.memoryDiscarded         := backend.io.memoryDiscarded
    io.memoryForwarded         := backend.io.memoryForwarded
    backend.io.allocate(0)     := io.allocate0
    backend.io.allocate(1)     := io.allocate1
    io.renamed0                := backend.io.renamed(0)
    io.renamed1                := backend.io.renamed(1)
    io.commit0                 := backend.io.commit(0)
    io.commit1                 := backend.io.commit(1)
    io.issued0                 := backend.io.issued(0)
    io.issued1                 := backend.io.issued(1)
    backend.io.commitEnable    := io.commitEnable
    backend.io.recover         := io.recover
    backend.io.inspectRegister := io.inspectRegister
    io.recoveryAccepted        := backend.io.recoveryAccepted
    io.recovering              := backend.io.recovering
    io.occupancy               := backend.io.occupancy
    io.headException           := backend.io.headException
    io.committedValue          := backend.io.committedValue
    io.redirect                := backend.io.redirect
}

object IntegerBackendGsimMain extends App {
    val target = args.headOption.getOrElse("build/gsim/integer")
    val p      = OooParams(
        speculativeRamBase = BigInt("80010000", 16),
        speculativeRamBytes = 4096,
        robEntries = args.lift(1).map(_.toInt).getOrElse(32),
        physicalRegs = args.lift(2).map(_.toInt).getOrElse(64),
        tagBits = args.lift(3).map(_.toInt).getOrElse(64)
    )
    ChiselStage.emitCHIRRTLFile(new IntegerBackendGsim(p), Array("--target-dir", target))
}
