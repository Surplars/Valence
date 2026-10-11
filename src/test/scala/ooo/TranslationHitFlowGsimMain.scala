package ooo

import _root_.circt.stage.ChiselStage

object TranslationHitFlowGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)), "output directory and flow 0|1 required")
    ChiselStage.emitCHIRRTLFile(new VirtualLoadPrecheckGsim(true, writeReadReuse = true,
        translationHitFlow = args(1) == "1"), Array("--target-dir", args(0)))
}
