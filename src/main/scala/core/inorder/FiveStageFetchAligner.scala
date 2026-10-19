package soc.core.inorder

import chisel3._
import chisel3.util._

/** C fetch alignment within IF, not an extra architectural pipeline stage.
  * First authorize an aligned 2-byte parcel. Reuse the containing word only with fetchSpan proof;
  * otherwise fetch/authorize parcel two separately, preserving its VA for a precise partial-fetch fault.
  * Held/killed core owners still drain. One parcel owner, no instruction FIFO or reset payload RAM.
  */
class FiveStageFetchAligner(p: FiveStageConfig) extends Module {
    require(p.withC)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(UInt(p.xlen.W)))
        val response = Decoupled(new FiveStageFetchResponse)
        val memoryRequest = Decoupled(new FiveStageDataRequest(p))
        val memoryResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val invalidate = if (p.fpgaTimingCuts) Some(Input(Bool())) else None
        val addressCandidates = if (p.fpgaTimingCuts) Some(Output(Vec(2, UInt(p.xlen.W)))) else None
        val candidateSecond = if (p.fpgaTimingCuts) Some(Output(Bool())) else None
    })
    if (p.fpgaTimingCuts) {
        val cuts = Module(new FiveStageFetchWordCuts(p))
        cuts.io.request <> io.request
        io.response <> cuts.io.response
        io.memoryRequest <> cuts.io.memoryRequest
        cuts.io.memoryResponse <> io.memoryResponse
        cuts.io.invalidate := io.invalidate.get
        io.addressCandidates.get := cuts.io.addressCandidates
        io.candidateSecond.get := cuts.io.candidateSecond
    } else {
        val idle :: firstWait :: secondSend :: secondWait :: Nil = Enum(4)
        val state = RegInit(idle)
        val pc = Reg(UInt(p.xlen.W)); val secondPc = Reg(UInt(p.xlen.W))
        val firstHalf = Reg(UInt(16.W))
        val offsetBits = log2Ceil(p.xlen / 8)
        val shifted = io.memoryResponse.bits.data >> Cat(pc(offsetBits - 1, 0), 0.U(3.W))
        val compressed = shifted(1, 0) =/= 3.U
        val unsupportedLong = shifted(4, 0) === 31.U
        val fits = pc(offsetBits - 1, 0) <= (p.xlen / 8 - 4).U
        val needSecond = !io.memoryResponse.bits.error && !compressed && !unsupportedLong &&
            !(fits && io.memoryResponse.bits.fetchSpan)
        val secondShifted = io.memoryResponse.bits.data >>
            Cat(secondPc(offsetBits - 1, 0), 0.U(3.W))
        io.response.valid := io.memoryResponse.valid &&
            (state === secondWait || (state === firstWait && !needSecond))
        io.response.bits.instruction := Mux(state === secondWait, Cat(secondShifted(15, 0), firstHalf),
            Mux(compressed || unsupportedLong, shifted(15, 0).pad(32), shifted(31, 0)))
        io.response.bits.compressed := state === firstWait && compressed && !io.memoryResponse.bits.error
        io.response.bits.error := io.memoryResponse.bits.error
        io.response.bits.pageFault := io.memoryResponse.bits.pageFault
        io.response.bits.secondHalfFault := state === secondWait
        io.memoryResponse.ready := Mux(state === firstWait && needSecond, true.B,
            (state === firstWait || state === secondWait) && io.response.ready)
        val slot = state === idle || io.response.fire
        io.request.ready := slot && io.memoryRequest.ready
        io.memoryRequest.valid := state === secondSend || (slot && io.request.valid)
        io.memoryRequest.bits := 0.U.asTypeOf(new FiveStageDataRequest(p))
        io.memoryRequest.bits.address := Mux(state === secondSend, secondPc, io.request.bits)
        io.memoryRequest.bits.size := 1.U
        when(io.response.fire) { state := idle }
        when(state === firstWait && needSecond && io.memoryResponse.fire) {
            firstHalf := shifted(15, 0); state := secondSend
        }
        when(state === secondSend && io.memoryRequest.fire) { state := secondWait }
        when(io.request.fire) {
            pc := io.request.bits; secondPc := io.request.bits + 2.U; state := firstWait
        }
        when(!reset.asBool) {
            assert(!io.memoryResponse.valid || state === firstWait || state === secondWait,
                "C parcel response without accepted owner")
            assert(!io.request.fire || !io.request.bits(0), "odd instruction PC")
        }
    }
}
