package platform

import _root_.circt.stage.ChiselStage
import soc.platform.CommonInterruptFabric

object CommonInterruptFabricGsimMain extends App {
    require(args.length == 1, "explicit fresh output directory required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonInterruptFabric, Array("--target-dir", args(0)))
}
