package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder._

/** Test-only scalar top: pinned GSIM misgenerates C++ getters for aggregate
  * Vec outputs. Retain both real address candidates, just expose them singly.
  * No DUT source, protocol, response edge or byte/fault oracle is changed.
  */
class I1FetchParcelTimingFixture(p: FiveStageConfig) extends Module {
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(UInt(p.xlen.W)))
        val response = Decoupled(new FiveStageFetchResponse)
        val memoryRequest = Decoupled(new FiveStageDataRequest(p))
        val memoryResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val invalidate = Input(Bool())
        val addressCandidate0 = Output(UInt(p.xlen.W))
        val addressCandidate1 = Output(UInt(p.xlen.W))
        val candidateSecond = Output(Bool())
    })
    val unit = Module(new FiveStageFetchAligner(p))
    unit.io.request <> io.request
    io.response <> unit.io.response
    io.memoryRequest <> unit.io.memoryRequest
    unit.io.memoryResponse <> io.memoryResponse
    unit.io.invalidate.get := io.invalidate
    io.addressCandidate0 := unit.io.addressCandidates.get(0)
    io.addressCandidate1 := unit.io.addressCandidates.get(1)
    io.candidateSecond := unit.io.candidateSecond.get
    when(io.memoryRequest.valid && !reset.asBool) {
        assert(io.memoryRequest.bits.address ===
            Mux(io.candidateSecond, io.addressCandidate1, io.addressCandidate0),
            "scalar test binding lost the selected real fetch address")
    }
}

object I1FetchParcelTimingMain extends App {
    val p = FiveStageConfig(xlen = args(1).toInt, withC = true,
        fpgaTimingCuts = true, pipelineProfile = "fpga8",
        instructionCacheBytes = 256, dataCacheBytes = 256,
        coherentCaches = args.contains("--predecode"), coherentCacheWays = 2,
        coherentControlCuts = args.contains("--predecode"), cacheFetchPredecode = args.contains("--predecode"))
    ChiselStage.emitCHIRRTLFile(new I1FetchParcelTimingFixture(p), Array("--target-dir", args.head))
}
