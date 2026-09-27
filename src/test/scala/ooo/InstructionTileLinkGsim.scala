package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.InstructionTileLinkBridge

object InstructionTileLinkBridgeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new InstructionTileLinkBridge, Array("--target-dir", args.head))
}

object InstructionTileLinkBridgeRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new InstructionTileLinkBridge,
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}

object TileLinkInstructionRomAdapterRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new soc.core.ooo.TileLinkInstructionRomAdapter(2048),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
