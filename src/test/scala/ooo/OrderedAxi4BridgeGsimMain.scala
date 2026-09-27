package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.OrderedAxi4Bridge

object OrderedAxi4BridgeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new OrderedAxi4Bridge, Array("--target-dir", args.head))
}

object OrderedAxi4BridgeRtlMain extends App {
    val addressWidth = args.lift(1).map(_.toInt).getOrElse(64)
    ChiselStage.emitSystemVerilogFile(
        new OrderedAxi4Bridge(addressWidth = addressWidth),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
