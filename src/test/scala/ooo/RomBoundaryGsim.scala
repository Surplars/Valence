package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.ip.tilelink.RegisteredTileLinkBoundary

class RomBoundaryGsim extends Module {
    private val params = TLParams(addrWidth = 64, sourceBits = 4)
    val io = IO(new Bundle {
        val upstream = Flipped(new TLBundle(params))
        val downstream = new TLBundle(params)
    })
    private val boundary = Module(new RegisteredTileLinkBoundary(params))
    boundary.io.upstream <> io.upstream
    io.downstream <> boundary.io.downstream
}

object RomBoundaryGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RomBoundaryGsim, Array("--target-dir", args.head))
}
