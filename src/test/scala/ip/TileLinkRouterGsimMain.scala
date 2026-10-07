package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.tilelink.TwoBankTileLinkRouter
import soc.bus.tilelink.{TLBundle, TLParams}

class TileLinkRouterGsim(prefixDecode: Boolean = false, rawReplies: Boolean = false) extends Module {
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val host  = Flipped(new TLBundle(params))
        val bank0 = new TLBundle(params)
        val bank1 = new TLBundle(params)
    })
    val router = Module(new TwoBankTileLinkRouter(params, prefixAddressDecode = prefixDecode,
        rawResponseMetadata = rawReplies))
    io.host  <> router.io.host
    io.bank0 <> router.io.banks(0)
    io.bank1 <> router.io.banks(1)
}

object TileLinkRouterGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkRouterGsim(args.drop(1).contains("prefix-decode"),
        args.drop(1).contains("raw-replies")),
        Array("--target-dir", args.head))
}

object TileLinkRouterRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new TwoBankTileLinkRouter,
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
