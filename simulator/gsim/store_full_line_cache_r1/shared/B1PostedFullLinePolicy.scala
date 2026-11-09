package soc.core.ooo

import chisel3._
import chisel3.util._

class B1PostedAcquireDecision(c: PostedStoreMergeConfig) extends PostedLineEvent(c) {
    val permissionOnly = Bool()
}

/** Metadata only. The caller owns payload, registered byte coverage and all tokens.
  * Allocation starts a monotonic bounded age; seal never cancels responsibility.
  * One registered decision per owner, held through backpressure and actual A fire.
  * No RAM, TileLink, CPU ordering or permission-grant implementation is implied.
  */
class B1PostedFullLinePolicy(c: PostedStoreMergeConfig, collectionCycles: Int = 256) extends Module {
    require(collectionCycles >= 2 && collectionCycles <= 65536)
    private val ageBits = log2Ceil(collectionCycles)
    val io = IO(new Bundle {
        val allocate = Input(Valid(new PostedLineEvent(c)))
        val allocateSealed = Input(Bool())
        val release = Input(Bool())
        val full = Input(Bool()) // Reduction of the owner's registered byte-valid mask.
        val seal = Input(Bool())
        val decision = Irrevocable(new B1PostedAcquireDecision(c))
        val joinOpen = Output(Bool())
        val accepted = Output(Bool())
        val permissionOnly = Output(Bool())
        val age = Output(UInt(ageBits.W))
    })
    val live = RegInit(false.B)
    val identity = Reg(new PostedLineEvent(c))
    val age = RegInit(0.U(ageBits.W))
    val decided = RegInit(false.B)
    val accepted = RegInit(false.B)
    val permissionOnly = RegInit(false.B)
    val expired = age === (collectionCycles - 1).U
    val close = live && (io.full || io.seal || expired)
    io.joinOpen := live && !decided && !close
    io.decision.valid := live && decided && !accepted
    io.decision.bits.context := identity.context
    io.decision.bits.reservation := identity.reservation
    io.decision.bits.permissionOnly := permissionOnly
    io.accepted := live && accepted
    io.permissionOnly := live && decided && permissionOnly
    io.age := age
    when(live && !decided) {
        when(!close) { age := age + 1.U }
        when(close) {
            decided := true.B
            permissionOnly := io.full
        }
    }
    when(io.decision.fire) { accepted := true.B }
    when(io.release) {
        assert(live && accepted, "full-line policy released an undecided/unaccepted owner")
        live := false.B
    }
    when(io.allocate.valid) {
        assert(!live && !io.release, "full-line policy reused a live owner")
        live := true.B
        identity := io.allocate.bits
        age := 0.U
        decided := io.allocateSealed
        accepted := false.B
        permissionOnly := false.B
    }
    val held = RegNext(io.decision.valid && !io.decision.ready, false.B)
    val heldBits = RegEnable(io.decision.bits.asUInt, io.decision.valid && !io.decision.ready)
    when(held) {
        assert(io.decision.valid && io.decision.bits.asUInt === heldBits,
            "full-line policy changed its held decision")
    }
}
