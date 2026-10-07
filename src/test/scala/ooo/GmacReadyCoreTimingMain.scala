package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo._

object GmacReadyCoreTimingMain extends App {
    val output = Path.of(args.head)
    require(!Files.exists(output), "fresh evidence directory required")
    ChiselStage.emitSystemVerilogFile(new MachineCore(
        BoardSocConfig.boardParams("staged-gmac-ready", externalDdr = true, isa = "rv64gc")),
        Array("--target-dir", output.toString), Array("--split-verilog", "-disable-all-randomization",
            "-strip-debug-info", "-default-layer-specialization=disable"))
}
