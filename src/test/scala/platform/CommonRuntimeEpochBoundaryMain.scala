package platform

import _root_.circt.stage.ChiselStage
import soc.platform.{CommonCpuTilePortParams, CommonRuntimeEpochBoundary}

/** Three real clocks around the actual boundary. Native tests drive public
  * endpoint ports, not private netlist state or a replacement CDC implementation.
  */
object CommonRuntimeEpochBoundaryMain extends App {
    require(args.length >= 1 && args.length <= 3, "fresh output directory [drain timeout] [cleanup timeout]")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    val drain = if (args.length >= 2) args(1).toInt else 64
    val cleanup = if (args.length >= 3) args(2).toInt else 128
    val p = CommonCpuTilePortParams(runtimeMaintenance = true, runtimeCancellation = true,
        runtimeInterruptHold = true)
    ChiselStage.emitSystemVerilogFile(new CommonRuntimeEpochBoundary(p, drain, cleanup),
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
