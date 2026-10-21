package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder._

/** Real eight-stage CPU, with externally delayed fetch/data replies and FENCE.I completion. */
class I1ExternalQuiesceHarness extends Module {
    val p = FiveStageConfig(withM = true, multiplyMode = "iterative", withA = true,
        pipelineProfile = "fpga8", fpgaTimingCuts = true, earlyMemoryIssue = true,
        pmpEntries = 4, overlapDataRetirement = true, externalFenceICompletion = true)
    val io = IO(new Bundle {
        val instructionRequest = Decoupled(UInt(64.W))
        val instructionResponse = Flipped(Decoupled(new FiveStageFetchResponse))
        val dataRequest = Decoupled(new FiveStageDataRequest(p))
        val dataResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val quiesceRequest = Input(Bool())
        val architecturalStopped = Output(Bool())
        val retire = Valid(new FiveStageRetire(p))
        val softwareIrq = Input(Bool())
        val trapTaken = Output(Bool())
        val trapPc = Output(UInt(64.W))
        val trapCause = Output(UInt(64.W))
        val fenceReady = Input(Bool())
        val fenceValid = Output(Bool())
        val fenceDrained = Output(Bool())
        val stageValid = Output(UInt(p.pipeline.size.W))
        val stallMulDiv = Output(Bool())
        val branchMispredict = Output(Bool())
        val instructions = Output(UInt(64.W))
    })
    val core = Module(new FiveStageCore(p, externalQuiesce = true))
    io.instructionRequest <> core.io.instructionRequest
    core.io.instructionResponse <> io.instructionResponse
    io.dataRequest <> core.io.dataRequest
    core.io.dataResponse <> io.dataResponse
    core.io.quiesceRequest.get := io.quiesceRequest
    io.architecturalStopped := core.io.architecturalStopped.get
    io.retire := core.io.retire
    io.trapTaken := core.io.trapTaken
    io.trapPc := core.io.trapPc
    io.trapCause := core.io.trapCause
    core.io.fenceIFlushReady.get := io.fenceReady
    io.fenceValid := core.io.fenceIFlush.get
    io.fenceDrained := core.io.fenceIFetchDrained.get
    io.stageValid := core.io.stageValid
    io.stallMulDiv := core.io.stallMulDiv
    io.branchMispredict := core.io.branchMispredict
    io.instructions := core.io.instructions
    core.io.time := 0.U
    core.io.externalIrq := false.B
    core.io.timerIrq := false.B
    core.io.softwareIrq := io.softwareIrq
}

object I1ExternalQuiesceMain extends App {
    require(args.length == 1, "output directory required")
    ChiselStage.emitCHIRRTLFile(new I1ExternalQuiesceHarness, Array("--target-dir", args(0)))
}
