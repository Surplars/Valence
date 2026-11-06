package inorder

import _root_.circt.stage.ChiselStage
import soc.core.inorder.FiveStageConfig

/** Matched M-mode CoreMark measurement of the CPU-side H/Sv39 feature cost. */
object I1HypervisorPerformanceMain extends App {
    val p = FiveStageConfig(withA = true, withC = true, withF = true, withD = true,
        withUser = true, withSupervisor = true, withSv39 = true, withH = true,
        multiplyMode = "dsp-tiled", pipelineProfile = "fpga8", fpgaTimingCuts = true,
        instructionCacheBytes = 32768, dataCacheBytes = 32768, branchPredictorEntries = 128,
        cacheFetchPredecode = true)
    ChiselStage.emitCHIRRTLFile(new I1PerformanceCachedCore(p), Array("--target-dir", args.head))
}
