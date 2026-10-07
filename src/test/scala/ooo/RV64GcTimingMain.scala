package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo._

/** Actual two-issue board CPU, with production instruction/data/system ports.
  * The surrounding cache/fabric, clock wizard, MIG and board constraints are
  * not included; OOC results must not be called whole-board qualification.
  */
object RV64GcTimingMain extends App {
    require(args.length == 1, "usage: RV64GcTimingMain fresh-output-directory")
    val output = Path.of(args.head).toAbsolutePath
    require(!Files.exists(output), "Preserve previous core timing evidence; use a fresh output directory")
    val p = BoardSocConfig.boardParams("staged-throughput", width = 2,
        externalDdr = true, isa = "rv64gc")
    ChiselStage.emitSystemVerilogFile(new MachineCore(p), Array("--target-dir", output.toString),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
