package soc.core.inorder

import chisel3._
import chisel3.util._

/** Native Spinor command, one irrevocable WB owner; full 80-bit identity. */
class I1SpinorCommand extends Bundle {
    val instruction = UInt(32.W)
    val scalar = UInt(64.W)
    val scalar2 = UInt(64.W)
    val avl = UInt(64.W)
    val token = UInt(80.W)
}

/** Published native result. Vector state remains in Spinor; FCSR remains in CPU. */
class I1SpinorResult extends Bundle {
    val token = UInt(80.W)
    val instruction = UInt(32.W)
    val scalar = UInt(64.W)
    val writesScalar = Bool()
    val illegal = Bool()
    val exception = Bool()
    val cause = UInt(64.W)
    val tval = UInt(64.W)
    val flagsValid = Bool()
    val flags = UInt(5.W)
}

/** CPU-local memory fault, bound to the complete native command identity.
  * The VPU still receives a denied D beat and owns its precise committed prefix.
  * Page/guest-page metadata stays in the CPU domain through native done.
  */
class I1SpinorMemoryFault extends Bundle {
    val token = UInt(80.W)
    val cause = UInt(64.W); val tval = UInt(64.W)
    val guest = new I1GuestFault
}

/** CPU-facing native preview/grant/done. WB retains ownership through done.fire.
  * The initial CPU binding finishes the current vector before taking interrupts;
  * it never sends stop or cancels an accepted command. Ports are CPU-clock local;
  * an independently clocked Spinor requires a complete transaction CDC boundary.
  */
class I1SpinorPort extends Bundle {
    val command = Decoupled(new I1SpinorCommand)
    val preview = Flipped(Valid(new I1SpinorResult))
    val grant = Decoupled(UInt(80.W))
    val done = Flipped(Decoupled(new I1SpinorResult))
    val frm = Output(UInt(3.W))
    val fflags = Output(UInt(5.W))
}

/** Native element service enters the same translation/atomic/cache path as scalar accesses. */
class I1SpinorMemoryPort(p: FiveStageConfig) extends Bundle {
    val request = Decoupled(new FiveStageDataRequest(p))
    val response = Flipped(Decoupled(new FiveStageDataResponse(p)))
}

/** CPU routing and scalar dependencies; Spinor performs complete instruction legality. */
object I1SpinorDecode {
    def csr(i: UInt): Bool = i(6, 0) === "h73".U && i(14, 12) =/= 0.U && i(14, 12) =/= 4.U &&
        Seq(0x008, 0x009, 0x00a, 0x00f, 0xc20, 0xc21, 0xc22).map(n => i(31, 20) === n.U).reduce(_ || _)
    def memory(i: UInt): Bool = (i(6, 0) === "h07".U || i(6, 0) === "h27".U) &&
        Seq(0, 5, 6, 7).map(n => i(14, 12) === n.U).reduce(_ || _)
    def routed(i: UInt): Bool = i(6, 0) === "h57".U || memory(i) || csr(i)
    def floating(i: UInt): Bool = i(6, 0) === "h57".U && (i(14, 12) === 1.U || i(14, 12) === 5.U)
    def floatingSource(i: UInt): Bool = i(6, 0) === "h57".U && i(14, 12) === 5.U
    def floatingDestination(i: UInt): Bool = (i & "hfe0ff07f".U) === "h42001057".U
    def integerLeft(i: UInt): Bool = memory(i) || (csr(i) && !i(14)) ||
        (i(6, 0) === "h57".U && (i(14, 12) === 4.U || i(14, 12) === 6.U ||
            (i(14, 12) === 7.U && i(31, 30) =/= 3.U)))
    def integerRight(i: UInt): Bool = (memory(i) && i(27, 26) === 2.U) ||
        (i(6, 0) === "h57".U && i(14, 12) === 7.U && i(31, 25) === "h40".U)
}
