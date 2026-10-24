package platform

import _root_.circt.stage.ChiselStage
import soc.platform._

object CommonA1RuntimeParkMain extends App {
    val p = CommonCpuTilePortParams(runtimeMaintenance = true, runtimeCancellation = true,
        runtimeInterruptHold = true)
    ChiselStage.emitSystemVerilogFile(new CommonA1RuntimePark(p), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
object CommonA1RuntimeTileMain extends App {
    val p = CommonCpuTilePortParams(runtimeMaintenance = true, runtimeCancellation = true,
        runtimeInterruptHold = true)
    ChiselStage.emitSystemVerilogFile(new CommonA1CpuTile(boundary = p), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}

/** Two retirement lanes, each independently Gray-encoded before AON summation. */
object CommonA1TelemetryMain extends App {
    ChiselStage.emitSystemVerilogFile(new soc.ip.clock.ClockPerformanceTelemetry(
        windowCycles = 128, width = 10, retirementLanes = 2), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
