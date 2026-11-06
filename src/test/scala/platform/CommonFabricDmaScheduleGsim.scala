package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.FpgaNextConfig

/** Explicit fabric-only controls. None changes a production preset or CPU configuration. */
object CommonFabricDmaSchedule {
    val modes: Set[String] = Set("default", "line", "threshold", "dual", "read-window")

    def config(mode: String): FpgaNextConfig = {
        require(modes.contains(mode), "expected default|line|threshold|dual|read-window")
        val selected = FpgaNextConfig.Selected
        if (mode == "default") selected
        else selected.copy(
            ddrWriteCollectionFlow = true,
            dmaLineTransfers = true,
            dmaLineEntries = if (Set("dual", "read-window").contains(mode)) 2 else 1,
            lineReadChannel = Set("dual", "read-window").contains(mode),
            dmaLineThresholdRewrite = mode != "line",
            dmaSingleReadWait = mode == "read-window"
        )
    }
}

/** Reproducible source emitter for the shared-fabric DMA experiment, not CPU IPC. */
object CommonFabricDmaScheduleGsimMain extends App {
    require(args.length == 2, "fresh output directory and DMA schedule mode required")
    require(!Files.exists(Paths.get(args(0))), "fresh output directory required")
    ChiselStage.emitCHIRRTLFile(
        new CommonMachineFabricFlatGsim(runtime = false, fpga = CommonFabricDmaSchedule.config(args(1))),
        Array("--target-dir", args(0))
    )
}
