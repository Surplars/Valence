package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo.{SynchronousDataRam, TileLinkDataRamAdapter}

class TileLinkBurstRamGsim extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
    })
    val adapter = Module(new TileLinkDataRamAdapter(params = params, burstEnabled = true))
    val ram = Module(new SynchronousDataRam(allowPartialWrites = true))
    io.tl <> adapter.io.tl
    adapter.io.memory <> ram.io.port
}

object TileLinkBurstRamGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkBurstRamGsim, Array("--target-dir", args.head))
}
