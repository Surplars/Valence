package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Dedicated verification only. Reference comparisons are not in production RTL. */
class ThreeProofRowSelectorGsim(rows: Int) extends Module {
    require(Set(1, 2, 3).contains(rows))
    val p = ThreeProofRowCandidateProfile.candidate.coreParams
    val io = IO(new Bundle {
        val records = Input(Vec(rows, new MemoryAddressProof(p)))
        val bound = Input(UInt(rows.W))
        val valid = Input(UInt(rows.W))
        val token = Input(new RobToken(p))
        val address = Input(UInt(64.W))
        val size = Input(UInt(3.W))
        val epoch = Input(UInt(32.W))
        val epochStable = Input(Bool())
        val mutation = Input(UInt(4.W))
        val selected = Output(new MemoryAddressProof(p))
        val rawReference = Output(new MemoryAddressProof(p))
        val authorizedReference = Output(new MemoryAddressProof(p))
        val permit = Output(Bool())
        val mutationReached = Output(Bool())
    })
    val raw = BoundStoreProofPayload.select(io.bound, io.records.toSeq, io.token.index)
    // Independent priority expression, not the candidate one-hot controls.
    val reference = if (rows == 1) io.records(0)
        else if (rows == 2)
            Mux(io.bound(0) && io.records(0).token.index === io.token.index, io.records(0), io.records(1))
        else Mux(io.bound(0) && io.records(0).token.index === io.token.index, io.records(0),
            Mux(io.bound(1) && io.records(1).token.index === io.token.index, io.records(1), io.records(2)))
    val exact = VecInit((0 until rows).map { r =>
        io.bound(r) && io.valid(r) && io.epochStable && io.records(r).epoch === io.epoch &&
            io.records(r).token.asUInt === io.token.asUInt && io.records(r).payload.address === io.address &&
            io.records(r).payload.size === io.size
    })
    val permitted = exact.asUInt.orR
    val authorized = Mux1H(exact, io.records)
    val checked = WireDefault(raw)
    when(io.mutation === 1.U && permitted) { checked.payload.physicalAddress := raw.payload.physicalAddress ^ 8.U }
    when(io.mutation === 2.U && permitted) { checked.token.tag := raw.token.tag ^ (BigInt(1) << 63).U }
    when(io.mutation === 3.U && permitted) { checked := io.records(0) }
    when(io.mutation === 4.U && permitted) { checked.payload.address := raw.payload.address ^ 8.U }
    when(io.mutation === 5.U && permitted) { checked.payload.mask := raw.payload.mask ^ 1.U }
    when(io.mutation === 6.U && permitted) { checked.payload.size := raw.payload.size ^ 1.U }
    when(io.mutation === 7.U && permitted) { checked.epoch := raw.epoch ^ 1.U }
    if (rows >= 2) { when(io.mutation === 8.U && permitted) { checked := io.records(1) } }
    if (rows == 3) { when(io.mutation === 9.U && permitted) { checked := io.records(2) } }
    io.mutationReached := permitted && io.mutation =/= 0.U && checked.asUInt =/= raw.asUInt
    io.selected := checked
    io.rawReference := reference
    io.authorizedReference := authorized
    io.permit := permitted
    assert(raw.asUInt === reference.asUInt, "all raw240 bits and fallback must match independent priority oracle")
    assert(PopCount(exact) <= 1.U, "exact authorization is at most one-hot")
    when(permitted) {
        assert(checked.asUInt === authorized.asUInt, "authorized full240-bit payload must match exact oracle")
    }
}

object ThreeProofRowSelectorGsimMain extends App {
    require(args.length == 2 && Set("1", "2", "3").contains(args(1)))
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))), "fresh output required")
    ChiselStage.emitCHIRRTLFile(new ThreeProofRowSelectorGsim(args(1).toInt), Array("--target-dir", args(0)))
}
