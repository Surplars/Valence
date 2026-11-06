package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

/** Matched retained read-overlap baseline versus DMA-only staged maintenance.
  * Both cases retain completion flow, two DMA tags and the same DDR service.
  */
object CommonFabricDmaProbeAcquireGsimMain extends App {
    require(args.length == 2, "fresh output directory and off|on DMA-Probe/Acquire selection required")
    val enabled = CommonFabricHomeCompletion.enabled(args(1))
    require(!Files.exists(Paths.get(args(0))), "fresh output directory required")
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabricFlatGsim(runtime = false,
        fpga = CommonFabricHomeCompletion.config, dmaMaintenanceCompletionFlow = true,
        dmaReadAcquireOverlap = true, dmaProbeAcquireOverlap = enabled), Array("--target-dir", args(0)))
}
