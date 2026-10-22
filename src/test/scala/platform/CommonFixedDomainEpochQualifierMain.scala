package platform

import _root_.circt.stage.ChiselStage
import soc.platform.{CommonCpuTilePortParams, CommonFixedDomainEpochQualifier}

/** Real production helper with independent fabric/fixed clocks; no idle model
  * or replacement CDC implementation is elaborated into the DUT.
  */
object CommonFixedDomainEpochQualifierMain extends App {
    require(args.length == 1, "fresh output directory")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    val p = CommonCpuTilePortParams(runtimeMaintenance = true, runtimeCancellation = true,
        runtimeInterruptHold = true)
    ChiselStage.emitSystemVerilogFile(new CommonFixedDomainEpochQualifier(p),
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
