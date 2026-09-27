package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.OrderedTileLinkBridge

object OrderedTileLinkBridgeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(
        new OrderedTileLinkBridge(
            orderedWrites = args.lift(1).contains("ordered") || args.lift(1).contains("mixed"),
            orderedMixedAccesses = args.lift(1).contains("mixed"),
            orderedWriteBankBytes = if (args.lift(1).contains("banked")) 2048 else 0,
            allowWriteErrors = args.lift(1).contains("ordered") || args.lift(1).contains("mixed"),
            flowHeadResponse = args.lift(2).contains("flow")
        ),
        Array("--target-dir", args.head)
    )
}

object OrderedTileLinkBridgeRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new OrderedTileLinkBridge,
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
