package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

/** Same retained two-tag, dual-read fabric and Home completion DATA path.
  * Only a disjoint CPU refill may enter beside already-dispatched DMA reads.
  */
object CommonFabricDmaAcquireGsimMain extends App {
    require(args.length == 2, "fresh output directory and off|on DMA-read/Acquire selection required")
    val enabled = CommonFabricHomeCompletion.enabled(args(1))
    require(!Files.exists(Paths.get(args(0))), "fresh output directory required")
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabricFlatGsim(runtime = false,
        fpga = CommonFabricHomeCompletion.config, dmaMaintenanceCompletionFlow = true,
        dmaReadAcquireOverlap = enabled), Array("--target-dir", args(0)))
}
