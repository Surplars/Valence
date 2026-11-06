package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.FpgaNextConfig

/** One opt-in Home control edge; all DMA, DDR, CPU/cache and service settings
  * are exactly the previously retained dual-read, two-tag fabric baseline.
  */
object CommonFabricHomeCompletion {
    def enabled(mode: String): Boolean = {
        require(Set("off", "on").contains(mode), "expected off|on")
        mode == "on"
    }
    def config: FpgaNextConfig = CommonFabricDmaSchedule.config("dual")
}

object CommonFabricHomeCompletionGsimMain extends App {
    require(args.length == 2, "fresh output directory and off|on completion-flow selection required")
    val enabled = CommonFabricHomeCompletion.enabled(args(1))
    require(!Files.exists(Paths.get(args(0))), "fresh output directory required")
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabricFlatGsim(runtime = false,
        fpga = CommonFabricHomeCompletion.config, dmaMaintenanceCompletionFlow = enabled),
        Array("--target-dir", args(0)))
}
