package soc.core.ooo

import chisel3._
import soc.bus.tilelink.TLBundle

/** Grant sinks belong only to the cache/home TL-C link. The home's backing
  * traffic is TL-UL: preserve the legacy one-bit fabric sink without truncating
  * a meaningful GrantAck. A/D payloads remain direct; unused E is explicitly0.
  */
object CoherentHomeUlBoundary {
    def connect(home: TLBundle, fabric: TLBundle): Unit = {
        require(home.a.bits.source.getWidth == fabric.a.bits.source.getWidth)
        require(home.d.bits.sink.getWidth >= fabric.d.bits.sink.getWidth)
        fabric.a <> home.a
        home.b <> fabric.b
        fabric.c <> home.c
        home.d <> fabric.d
        fabric.e.valid := home.e.valid
        fabric.e.bits.sink := 0.U
        home.e.ready := fabric.e.ready
        assert(!home.c.valid && !home.e.valid, "home backing port must not emit coherent C/E traffic")
    }
}
