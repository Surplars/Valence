package ooo

import _root_.circt.stage.ChiselStage
import chisel3.RawModule
import java.nio.file.{Files, Path}
import soc.core.ooo._

/** Full-FPU timing baseline/candidate, real production modules and port contracts.
  * No extra measurement registers or tied-off datapaths. 10 ns OOC comparison
  * must distinguish register-register timing from zero-delay boundary artifacts.
  */
object FloatingPointFullTimingMain extends App {
    require(args.length == 1, "usage: FloatingPointFullTimingMain fresh-output-directory")
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "Preserve previous timing evidence: use a fresh output directory")
    val p = BoardSocConfig.timingParams("staged-throughput", 2).copy(
        machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3,
        floatingPoint = FloatingPointConfig.fullFD)
    val options = Array("-disable-all-randomization", "-strip-debug-info",
        "-default-layer-specialization=disable")
    def emit(name: String)(unit: => RawModule): Unit = {
        ChiselStage.emitSystemVerilogFile(unit,
            Array("--target-dir", output.resolve(name).toString), options)
    }
    for (double <- Seq(false, true)) {
        val suffix = if (double) "D" else "S"
        for (operation <- Seq("add", "multiply", "fused")) {
            emit(s"FloatingPoint${operation.capitalize}$suffix") {
                new FloatingPointArithmetic(p, double, operation)
            }
        }
        emit(s"FloatingPointDivSqrt$suffix") { new FloatingPointDivSqrt(p, double, true, true) }
        emit(s"FloatingPointMisc$suffix") { new FloatingPointMisc(p, double, p.fpConfig) }
    }
    emit("FloatingPointState") { new FloatingPointState(p) }
    emit("FloatingPointExecute") { new FloatingPointExecute(p, p.fpConfig) }
    emit("FloatingPointSystem") { new FloatingPointSystem(p) }
    emit("FloatingPointMemoryPipeline") { new FloatingPointMemoryPipeline(p) }
}
