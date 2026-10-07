package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.ip.tilelink.TwoMasterTwoBankTileLinkCrossbar

class TileLinkCrossbarGsim(prefixDecode: Boolean = false, rawReplies: Boolean = false,
    rawRequests: Boolean = false) extends Module {
    val upstream = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val master0 = Flipped(new TLBundle(upstream))
        val master1 = Flipped(new TLBundle(upstream))
        val bank0 = new TLBundle(upstream.copy(sourceBits = 4))
        val bank1 = new TLBundle(upstream.copy(sourceBits = 4))
    })
    val crossbar = Module(new TwoMasterTwoBankTileLinkCrossbar(upstream, prefixAddressDecode = prefixDecode,
        rawResponseMetadata = rawReplies, rawRequestMetadata = rawRequests))
    io.master0 <> crossbar.io.masters(0)
    io.master1 <> crossbar.io.masters(1)
    io.bank0 <> crossbar.io.banks(0)
    io.bank1 <> crossbar.io.banks(1)
}

object TileLinkCrossbarGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkCrossbarGsim(args.drop(1).contains("prefix-decode"),
        args.drop(1).contains("raw-replies"), args.drop(1).contains("raw-requests")),
        Array("--target-dir", args.head))
}

object TileLinkCrossbarRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new TwoMasterTwoBankTileLinkCrossbar,
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
