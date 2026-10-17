package soc.core.ooo

import chisel3._
import soc.bus.tilelink.TLBundle

/** Grant sinks belong only to the cache/home TL-C link. The home's backing
  * traffic is TL-UL: preserve the legacy one-bit fabric sink without truncating
  * a meaningful GrantAck. Optional A buffering has two non-flow-through slots with occupancy-only
  * input ready. D stays direct; source allocation and burst locking remain in
  * the adjacent writer/arbiter. Unused E is explicitly zero.
  */
object CoherentHomeUlBoundary {
    def connect(home: TLBundle, fabric: TLBundle, registerRequests: Boolean = false): Unit = {
        require(home.a.bits.source.getWidth == fabric.a.bits.source.getWidth)
        require(home.d.bits.sink.getWidth >= fabric.d.bits.sink.getWidth)
        if (registerRequests) {
            val requests = Module(new soc.ip.bus.TwoEntryRegisterQueue(chiselTypeOf(fabric.a.bits))).suggestName("homeRequests")
            requests.io.enq <> home.a
            fabric.a <> requests.io.deq
        } else fabric.a <> home.a
        home.b <> fabric.b
        fabric.c <> home.c
        home.d <> fabric.d
        fabric.e.valid := home.e.valid
        fabric.e.bits.sink := 0.U
        home.e.ready := fabric.e.ready
        assert(!home.c.valid && !home.e.valid, "home backing port must not emit coherent C/E traffic")
    }
}
