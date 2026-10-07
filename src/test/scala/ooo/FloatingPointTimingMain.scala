package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import java.nio.file.{Files, Path}

/** Production FP units, exported separately at the two-issue board capacity.
  * No extra measurement registers, tied-off handshakes or relaxed FP datapaths.
  * OOC boundary delays are a comparison convention, not whole-board signoff.
  */
object FloatingPointTimingMain extends App {
    require(args.length == 1, "usage: FloatingPointTimingMain fresh-output-directory")
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "Preserve old measurements: use a fresh output directory")
    val p = BoardSocConfig.timingParams("staged-throughput", 2)
        .copy(machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3,
            experimentalFloatingPoint = true)
    val options = Array("-disable-all-randomization", "-strip-debug-info",
        "-default-layer-specialization=disable")
    ChiselStage.emitSystemVerilogFile(new FloatingPointAdd(p),
        Array("--target-dir", output.resolve("FloatingPointAdd").toString), options)
    ChiselStage.emitSystemVerilogFile(new FloatingPointState(p),
        Array("--target-dir", output.resolve("FloatingPointState").toString), options)
    ChiselStage.emitSystemVerilogFile(new FloatingPointSystem(p),
        Array("--target-dir", output.resolve("FloatingPointSystem").toString), options)
}
