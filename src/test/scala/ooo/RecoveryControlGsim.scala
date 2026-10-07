package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Scalar input/output naming for GSIM; packed tags are set by a complete sweep. */
class RecoveryControlGsim(entries: Int) extends Module {
    private val p = OooParams(robEntries = entries, tagBits = 64)
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val count = Input(UInt(p.countBits.W))
        val recovering = Input(Bool())
        val keepCount = Input(UInt(p.countBits.W))
        val tagWrite = Input(Bool())
        val tagIndex = Input(UInt(p.robBits.W))
        val tagValue = Input(UInt(64.W))
        val external = Input(Valid(new RecoveryRequest(p)))
        val local = Input(Valid(new RecoveryRequest(p)))
        val externalAccepted = Output(Bool())
        val externalWins = Output(Bool())
        val selected = Output(Valid(new RecoveryRequest(p)))
        val accepted = Output(Bool())
        val activeKeep = Output(UInt(p.countBits.W))
        val killed = Output(UInt(entries.W))
        val survives = Output(UInt(entries.W))
        val localRedirect = Input(Valid(new RobToken(p)))
        val trapRedirect = Input(Valid(new RobToken(p)))
        val query0 = Input(new RobToken(p))
        val query1 = Input(new RobToken(p))
        val match0 = Output(Bool())
        val match1 = Output(Bool())
    })
    val tags = RegInit(VecInit(Seq.fill(entries)(0.U(64.W))))
    when(io.tagWrite) { tags(io.tagIndex) := io.tagValue }
    val admission = Module(new ParallelRecoveryAdmission(p))
    admission.io.tags := tags
    admission.io.head := io.head
    admission.io.count := io.count
    admission.io.recovering := io.recovering
    admission.io.keepCount := io.keepCount
    admission.io.external := io.external
    admission.io.local := io.local
    io.externalAccepted := admission.io.externalAccepted
    io.externalWins := admission.io.externalWins
    io.selected := admission.io.selected
    io.accepted := admission.io.accepted
    io.activeKeep := admission.io.activeKeep
    io.killed := admission.io.killed
    io.survives := admission.io.survives
    val matching = Module(new RedirectTokenQualification(p))
    matching.io.local := io.localRedirect
    matching.io.trap := io.trapRedirect
    matching.io.queries(0) := io.query0
    matching.io.queries(1) := io.query1
    io.match0 := matching.io.matches(0)
    io.match1 := matching.io.matches(1)
}

object RecoveryControlGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RecoveryControlGsim(args.lift(1).map(_.toInt).getOrElse(16)),
        Array("--target-dir", args.head))
}

/** Reuse the independent fixed-32-bit, DIRECT-IRQ CSR/IRQ oracle unchanged.
  * Compressed-frontend helpers, RAM geometry and the separate IMSIC output
  * pipeline differ; backend recovery/redirect/retirement and full64 ownership
  * are identical. This verifies the backend IRQ boundary, NOT production's
  * one-cycle registered IMSIC level. Both old/new registered fixtures fail the
  * original oracle's zero-delay eligibility rule and their evidence is retained.
  */
object RecoveryMachineCoreGsimMain extends App {
    val p = BoardSocConfig.timingParams(args.lift(1).getOrElse("staged-recovery-control")).copy(
        compressedInstructions = false, parallelReturnStackControl = false,
        rawFetchPresence = false, alignedFetchPmp = false, parallelFetchTagLookup = false,
        parallelFetchAlignment = false,
        registeredImsicInterrupts = args.drop(2).contains("registered-irq"),
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096)
    ChiselStage.emitCHIRRTLFile(new MachineCoreGsim(p), Array("--target-dir", args.head))
}
