package soc.core.ooo

import chisel3._
import chisel3.util._

/** Disposable numerical operands only: no PA, permission, context epoch or accepted-request ownership. */
class PreparedHeadStorePayload(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val address = UInt(64.W)
    val data = UInt(64.W)
    val size = UInt(2.W)
}

/** One optional preparation row, not a queue or a memory transaction.
  *
  * Capacity 1, minimum latency 1, pre-head refresh II 1, no empty bypass.
  * A live current-head owner holds every payload bit until actual issue, owner
  * death or flush. Consumption creates an empty cycle: it cannot enable wide
  * payload capture on the same edge. Missing preparation must use caller fallback;
  * this row must never contribute to memoryBusy, drain or architectural authority.
  *
  * ownerLive and atHead describe the REGISTERED token using the caller's current
  * full-token owner/head checks. Neither may depend on commit, ready or issue fire.
  * Output is raw registered state, including on a flush/consume cycle. The caller
  * must apply final ownership, ordering, translation, permission and kill checks.
  *
  * Validity priority: flush; matching consume; early replacement; dead owner;
  * retention. Payload capture deliberately ignores all late controls, even flush.
  * At 16 ROB entries and 64-bit tags the row is 198 payload bits plus one valid bit.
  */
class PreparedHeadStoreOperands(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val candidate = Flipped(Valid(new PreparedHeadStorePayload(p)))
        val ownerLive = Input(Bool())
        val atHead = Input(Bool())
        val flush = Input(Bool())
        val consume = Flipped(Valid(new RobToken(p)))
        val prepared = Output(Valid(new PreparedHeadStorePayload(p)))
    })

    val valid = RegInit(false.B)
    val payload = Reg(new PreparedHeadStorePayload(p))
    io.prepared.valid := valid
    io.prepared.bits := payload

    val liveHead = valid && io.ownerLive && io.atHead
    val capture = io.candidate.valid && !liveHead
    val consumeMatches = io.consume.bits.asUInt === payload.token.asUInt
    val consumed = io.consume.valid && consumeMatches

    // The sole wide-register enable has no consume/ready/commit/flush input.
    when(capture) { payload := io.candidate.bits }
    when(io.flush || consumed) {
        valid := false.B
    }.elsewhen(capture) {
        valid := true.B
    }.elsewhen(!io.ownerLive) {
        valid := false.B
    }

    when(io.consume.valid) {
        assert(valid, "prepared head store consume requires registered valid")
        assert(io.ownerLive, "prepared head store consume requires live owner")
        assert(io.atHead, "prepared head store consume requires current head")
        assert(consumeMatches, "prepared head store consume requires exact full token")
        assert(!io.flush, "prepared head store consume forbidden during flush")
    }
}
