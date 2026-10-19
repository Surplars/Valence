package platform

import _root_.circt.stage.ChiselStage
import soc.platform.CommonFabricScalarArbiter

/** Direct shared scalar boundary, without a CPU adapter or a memory-model RTL oracle. */
object CommonMachineFabricScalarGsimMain extends App {
    require(args.length == 1, "explicit fresh output directory required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonFabricScalarArbiter(capacity = 16), Array("--target-dir", args(0)))
}
