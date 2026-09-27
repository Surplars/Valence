package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo.{SynchronousDataRam, TileLinkDataRamAdapter}
import soc.ip.tilelink.TwoBankTileLinkRouter

/** The two-bank simulation RAM topology, with burst-capable managers on both banks. */
class TileLinkSplitBurstRamGsim extends Module {
    private val base = BigInt("80010000", 16)
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
    })
    val router = Module(new TwoBankTileLinkRouter(params))
    io.tl <> router.io.host
    for (i <- 0 until 2) {
        val manager = Module(new TileLinkDataRamAdapter(params = params,
            burstEnabled = true, burstBase = base + i * 2048, burstBytes = 2048))
        val ram = Module(new SynchronousDataRam(bytes = 2048, base = base + i * 2048))
        router.io.banks(i) <> manager.io.tl
        manager.io.memory <> ram.io.port
    }
}

object TileLinkSplitBurstRamGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkSplitBurstRamGsim, Array("--target-dir", args.head))
}
