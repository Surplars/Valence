package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.bus.TwoEntryRegisterQueue

/** Payload-only proofs cross the EXISTING two-entry request boundary.
  * No extra latency, ownership, source, AXI slot or full-queue credit borrowing.
  */
class I1AxiPreflight(addressWidth: Int) extends Bundle {
    val window = Bool()
    val axiAddress = UInt(addressWidth.W)
    // collect, read-address, read-denied, single-write-address, single-write-denied
    val initialPhases = UInt(5.W)
}
object I1AxiPreflight {
    def apply(a: TLBundleA, addressWidth: Int, base: BigInt, bytes: BigInt, burstBeats: Int): I1AxiPreflight = {
        val v = Wire(new I1AxiPreflight(addressWidth))
        val window = I1AddressWindow.contains(a.address, base, bytes)
        val allowed = window && a.size <= (log2Ceil(burstBeats) + 3).U
        val read = a.opcode === TLOpcode.Get
        val single = a.size <= 3.U
        v.window := window
        v.axiAddress := a.address(addressWidth - 1, 0) -
            (base & ((BigInt(1) << addressWidth) - 1)).U(addressWidth.W)
        v.initialPhases := VecInit(Seq(!read && !single, read && allowed, read && !allowed,
            !read && single && allowed, !read && single && !allowed)).asUInt
        v
    }
}
class I1RegisteredAxiRequestBoundary(params: TLParams, addressWidth: Int,
    base: BigInt, bytes: BigInt, burstBeats: Int) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new TLBundle(params))
        val downstream = new TLBundle(params)
        val preflight = Output(new I1AxiPreflight(addressWidth))
    })
    val requests = Module(new TwoEntryRegisterQueue(new Bundle {
        val request = new TLBundleA(params)
        val proof = new I1AxiPreflight(addressWidth)
    }))
    requests.io.enq.valid := io.upstream.a.valid
    io.upstream.a.ready := requests.io.enq.ready
    requests.io.enq.bits.request := io.upstream.a.bits
    requests.io.enq.bits.proof := I1AxiPreflight(io.upstream.a.bits, addressWidth, base, bytes, burstBeats)
    io.downstream.a.valid := requests.io.deq.valid
    io.downstream.a.bits := requests.io.deq.bits.request
    requests.io.deq.ready := io.downstream.a.ready
    io.preflight := requests.io.deq.bits.proof
    val replies = Module(new TwoEntryRegisterQueue(new TLBundleD(params)))
    replies.io.enq <> io.downstream.d
    io.upstream.d <> replies.io.deq
    io.upstream.b <> io.downstream.b
    io.downstream.c <> io.upstream.c
    io.downstream.e <> io.upstream.e
    assert(!io.upstream.c.valid && !io.upstream.e.valid && !io.downstream.b.valid,
        "AXI preflight boundary is downstream of the coherent Home only")
}
class I1RegisteredAxiLineRequestBoundary(addressWidth: Int, base: BigInt,
    bytes: BigInt, burstBeats: Int) extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val upstream = Flipped(new soc.ip.tilelink.LineReadMemoryPort())
        val downstream = new soc.ip.tilelink.LineReadMemoryPort()
        val preflight = Output(new I1AxiPreflight(addressWidth))
    })
    val requests = Module(new TwoEntryRegisterQueue(new Bundle {
        val request = new soc.ip.tilelink.LineFillRequest(64, 8)
        val proof = new I1AxiPreflight(addressWidth)
    }))
    val synthetic = WireDefault(0.U.asTypeOf(new TLBundleA(params)))
    synthetic.opcode := TLOpcode.Get; synthetic.size := 6.U
    synthetic.address := io.upstream.request.bits.address
    requests.io.enq.valid := io.upstream.request.valid
    io.upstream.request.ready := requests.io.enq.ready
    requests.io.enq.bits.request := io.upstream.request.bits
    requests.io.enq.bits.proof := I1AxiPreflight(synthetic, addressWidth, base, bytes, burstBeats)
    io.downstream.request.valid := requests.io.deq.valid
    io.downstream.request.bits := requests.io.deq.bits.request
    requests.io.deq.ready := io.downstream.request.ready
    io.preflight := requests.io.deq.bits.proof
    io.upstream.response <> io.downstream.response
}
