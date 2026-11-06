package spinor_integration

import _root_.circt.stage.ChiselStage
import soc.core.inorder._

object I1PackedFetchMain extends App {
    val p = FiveStageConfig(withC = true, pipelineProfile = "fpga8", fpgaTimingCuts = true,
        instructionCacheBytes = 32768, cacheFetchPredecode = true)
    ChiselStage.emitCHIRRTLFile(new FiveStageWordCache(p, 32768, allowHitReplacement = true),
        Array("--target-dir", args.head))
}
object I1PredecodeDataCacheMain extends App {
    val p = FiveStageConfig(withC = true, pipelineProfile = "fpga8", fpgaTimingCuts = true,
        instructionCacheBytes = 32768, cacheFetchPredecode = true)
    ChiselStage.emitCHIRRTLFile(new FiveStageWordCache(p, 512), Array("--target-dir", args.head))
}
