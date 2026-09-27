package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class IntegerCoreGsim(p: OooParams) extends Module {
    require(p.renameWidth == 2 && p.commitWidth == 2)
    require(Set(4, 8).contains(p.memoryEntries), "GSIM harness checks four or eight memory slots")
    require(p.branchPredictorEntries == 64, "GSIM predictor model uses 64 entries")
    val io = IO(new Bundle {
        val instruction0      = Input(Valid(UInt(32.W)))
        val instruction1      = Input(Valid(UInt(32.W)))
        val fetchPc           = Output(UInt(64.W))
        val accepted0         = Output(Bool())
        val accepted1         = Output(Bool())
        val commitEnable      = Input(Bool())
        val commit0           = Output(Valid(new CommitRecord(p)))
        val commit1           = Output(Valid(new CommitRecord(p)))
        val exception         = Output(Valid(new HeadException(p)))
        val occupancy         = Output(UInt(p.countBits.W))
        val inspectRegister   = Input(UInt(5.W))
        val committedValue    = Output(UInt(64.W))
        val redirect          = Output(Valid(new FrontendRedirect(p)))
        val recovering        = Output(Bool())
        val memory            = new DataPort
        val memoryBusy        = Output(Bool())
        val issueCount        = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val memoryDiscarded   = Output(Bool())
        val memoryForwarded   = Output(Bool())
        val mulDivCancelled   = Output(Bool())
        val mulDivOverlap     = Output(Bool())
        val mulDivBlocked     = Output(Bool())
        val mulDivConcurrent  = Output(Bool())
        val mulDivMultiCancel = Output(Bool())
        // Independent decoder observation allows exhaustive encoding-field checks without executing illegal streams.
        val decodeInstruction = Input(UInt(32.W))
        val decodePc          = Input(UInt(64.W))
        val decoded           = Output(new IntegerRequest)
        val decodeLegal       = Output(Bool())
    })
    val core = Module(new IntegerCore(p))
    io.memory <> core.io.memory
    io.memoryBusy           := core.io.memoryBusy
    io.issueCount           := core.io.issueCount
    io.memoryDiscarded      := core.io.memoryDiscarded
    io.memoryForwarded      := core.io.memoryForwarded
    io.mulDivCancelled      := core.io.mulDivCancelled
    io.mulDivOverlap        := core.io.mulDivOverlap
    io.mulDivBlocked        := core.io.mulDivBlocked
    io.mulDivConcurrent     := core.io.mulDivConcurrent
    io.mulDivMultiCancel    := core.io.mulDivMultiCancel
    core.io.instructions(0) := io.instruction0
    core.io.instructions(1) := io.instruction1
    core.io.instructionFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
    core.io.instructionPageFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
    core.io.commitEnable    := io.commitEnable
    core.io.inspectRegister := io.inspectRegister
    io.fetchPc              := core.io.fetchPc
    io.accepted0            := core.io.accepted(0)
    io.accepted1            := core.io.accepted(1)
    io.commit0              := core.io.commit(0)
    io.commit1              := core.io.commit(1)
    io.exception            := core.io.exception
    io.occupancy            := core.io.occupancy
    io.committedValue       := core.io.committedValue
    io.redirect             := core.io.redirect
    io.recovering           := core.io.recovering
    val decode = Module(new IntegerDecode)
    decode.io.instruction := io.decodeInstruction
    decode.io.pc          := io.decodePc
    io.decoded            := decode.io.decoded
    io.decodeLegal        := decode.io.legal
}

object IntegerCoreGsimMain extends App {
    val target = args.headOption.getOrElse("build/gsim/core")
    val p      = OooParams(
        speculativeRamBase = BigInt("80010000", 16),
        speculativeRamBytes = 4096,
        bufferedRamStores = true,
        robEntries = args.lift(1).map(_.toInt).getOrElse(32),
        physicalRegs = args.lift(2).map(_.toInt).getOrElse(64),
        memoryEntries = args.lift(4).map(_.toInt).getOrElse(4),
        fastBufferedStoreRetire = args.lift(5).contains("fast-store"),
        fastHeadLoadRetire = args.lift(6).contains("fast-load"),
        loadCompletionBypass = args.lift(7).contains("load-bypass"),
        moveAlias = args.lift(8).contains("move-alias"),
        mulWordPreviewBypass = args.lift(9).contains("word-bypass"),
        indirectTargetEntries = args.lift(10).map(_.toInt).getOrElse(0)
    )
    ChiselStage.emitCHIRRTLFile(new IntegerCoreGsim(p), Array("--target-dir", target))
}
