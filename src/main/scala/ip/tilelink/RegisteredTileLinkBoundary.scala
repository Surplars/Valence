package soc.ip.tilelink

import chisel3._
import soc.bus.tilelink._
import soc.ip.bus.TwoEntryRegisterQueue

/** TL-UL timing boundary. A and D each have two registered beat slots, latency
  * +1 in each direction, II=1, and occupancy-only input ready. Every field,
  * including source/error/mask/corrupt, travels with its beat; no source is
  * allocated or rewritten here. Multibeat messages remain FIFO ordered.
  * C/E/B are unbuffered and must be inactive at this non-coherent boundary.
  */
class RegisteredTileLinkBoundary(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new TLBundle(params))
        val downstream = new TLBundle(params)
    })
    val requests = Module(new TwoEntryRegisterQueue(new TLBundleA(params)))
    val replies = Module(new TwoEntryRegisterQueue(new TLBundleD(params)))
    requests.io.enq <> io.upstream.a
    io.downstream.a <> requests.io.deq
    replies.io.enq <> io.downstream.d
    io.upstream.d <> replies.io.deq
    io.upstream.b <> io.downstream.b
    io.downstream.c <> io.upstream.c
    io.downstream.e <> io.upstream.e
    assert(!io.upstream.c.valid && !io.upstream.e.valid && !io.downstream.b.valid,
        "registered fabric boundary accepts TL-UL traffic only")
}
