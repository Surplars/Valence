package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo._

object EthernetTimingMain extends App {
    require(args.nonEmpty && args.length <= 7,
        "usage: EthernetTimingMain output [isa] [board] [profile] [dma] [instruction-cache-lines] [data-cache-lines]")
    val output = Path.of(args.head)
    require(!Files.exists(output), "fresh evidence directory required")
    val isa = args.lift(1).getOrElse("rv64gc")
    val board = args.lift(2).contains("board")
    val profile = args.lift(3).getOrElse("staged-ethernet")
    if (board) ChiselStage.emitSystemVerilogFile(new EthernetSocTop(isa, profile,
        packetDma = args.lift(4).contains("dma"),
        instructionLineCacheLines = args.lift(5).map(_.toInt).getOrElse(8),
        dataCacheLines = args.lift(6).map(_.toInt).getOrElse(32)),
        Array("--target-dir", output.toString), Array("--split-verilog", "-disable-all-randomization",
            "-strip-debug-info", "-default-layer-specialization=disable"))
    else ChiselStage.emitSystemVerilogFile(new MachineCore(
        BoardSocConfig.boardParams(profile, externalDdr = true, isa = isa)),
        Array("--target-dir", output.toString), Array("--split-verilog", "-disable-all-randomization",
            "-strip-debug-info", "-default-layer-specialization=disable"))
}
