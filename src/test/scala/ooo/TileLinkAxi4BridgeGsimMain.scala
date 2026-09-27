package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.TileLinkAxi4Bridge

object TileLinkAxi4BridgeGsimMain extends App {
    val addressWidth = args.lift(1).map(_.toInt).getOrElse(64)
    val maxWrites = args.lift(2).map(_.toInt).getOrElse(4)
    ChiselStage.emitCHIRRTLFile(new TileLinkAxi4Bridge(axiAddressWidth = addressWidth, maxWrites = maxWrites),
        Array("--target-dir", args.head))
}

object TileLinkAxi4BridgeRtlMain extends App {
    val addressWidth = args.lift(1).map(_.toInt).getOrElse(64)
    ChiselStage.emitSystemVerilogFile(
        new TileLinkAxi4Bridge(axiAddressWidth = addressWidth),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
