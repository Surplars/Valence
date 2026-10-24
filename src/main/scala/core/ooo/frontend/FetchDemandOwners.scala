package soc.core.ooo

import chisel3._
import chisel3.util._

class FetchDemandOffer extends Bundle {
    val base = UInt(64.W)
    val context = UInt(3.W)
    val mask = UInt(2.W)
}

class FetchDemandOwner(keyCount: Int) extends Bundle {
    val base = UInt(64.W)
    val plusEight = UInt(64.W)
    val minus = Vec(keyCount, UInt(64.W))
    val context = UInt(3.W)
    val stale = Bool()
}

/** Two ordered, accepted 8B demands and a separately held offer reservation.
  * No data bypass or extra request/return edge. A response uses the OLD head;
  * only its handshake releases an accepted owner. Accepted + held reservation
  * never exceeds two after an edge. Invalidate marks obligations, never drops
  * them. Physical responses are required to be ordered and exactly once.
  */
class FetchDemandOwners(keyCount: Int = 3) extends Module {
    require(keyCount >= 1)
    val io = IO(new Bundle {
        val candidate = Input(Valid(new FetchDemandOffer))
        val request = Decoupled(new FetchDemandOffer)
        val response = Input(Bool())
        val invalidate = Input(Bool())
        val queryBase = Input(Vec(2, UInt(64.W)))
        val queryContext = Input(UInt(3.W))
        val owned = Output(Vec(2, Bool()))
        val head = Output(new FetchDemandOwner(keyCount))
        val headValid = Output(Bool())
        val credit = Output(Bool())
        val held = Output(Bool())
        val quiescent = Output(Bool())
    })
    val entries = Reg(Vec(2, new FetchDemandOwner(keyCount)))
    val valid = RegInit(VecInit(Seq.fill(2)(false.B)))
    val head = RegInit(false.B)
    val tail = RegInit(false.B)
    val count = RegInit(0.U(2.W))
    val held = RegInit(false.B)
    val heldOffer = Reg(new FetchDemandOffer)
    val heldStale = RegInit(false.B)
    io.head := entries(head.asUInt)
    io.headValid := count =/= 0.U
    io.credit := count < 2.U || io.response
    io.held := held
    io.quiescent := count === 0.U && !held
    for (query <- 0 until 2) {
        io.owned(query) := (0 until 2).map(slot => valid(slot) && !entries(slot).stale &&
            entries(slot).base === io.queryBase(query) && entries(slot).context === io.queryContext).reduce(_ || _)
    }
    io.request.valid := !reset.asBool && (held || (io.candidate.valid && io.credit))
    io.request.bits := Mux(held, heldOffer, io.candidate.bits)
    when(io.request.valid && !io.request.ready && !held) {
        held := true.B
        heldOffer := io.request.bits
        heldStale := io.invalidate
    }
    when(io.invalidate) {
        for (slot <- 0 until 2) { when(valid(slot)) { entries(slot).stale := true.B } }
        when(held) { heldStale := true.B }
    }
    when(io.response) {
        assert(count =/= 0.U && valid(head.asUInt), "fetch response has no accepted demand owner")
        valid(head.asUInt) := false.B
        head := !head
    }
    when(io.request.fire) {
        assert(io.credit, "fetch accepted a demand without return credit")
        valid(tail.asUInt) := true.B
        entries(tail.asUInt).base := io.request.bits.base
        entries(tail.asUInt).plusEight := io.request.bits.base + 8.U
        for (key <- 0 until keyCount) {
            entries(tail.asUInt).minus(key) := io.request.bits.base - (8 * (key + 1)).U
        }
        entries(tail.asUInt).context := io.request.bits.context
        entries(tail.asUInt).stale := io.invalidate || (held && heldStale)
        tail := !tail
        held := false.B
        heldStale := false.B
    }
    when(io.request.fire =/= io.response) {
        count := Mux(io.request.fire, count + 1.U, count - 1.U)
    }
    assert(count <= 2.U && PopCount(valid) === count, "fetch demand ownership count mismatch")
    assert(!held || count < 2.U, "held fetch offer must retain its reserved slot")
}
