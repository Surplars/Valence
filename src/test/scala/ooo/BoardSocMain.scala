package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo.{BoardSocConfig, BoardSocTop}

/** Export a board clock profile; blk_mem_gen_0 and XPM_MEMORY are supplied by Vivado. */
object BoardSocMain extends App {
    require(args.length >= 1 && args.length <= 10,
        "usage: BoardSocMain output-directory [clock-hz] [ddr] " +
            "[baseline|early-issue|queued-memory|registered-response|registered-replay|staged-fabric|staged-control|staged-data|staged-execute|staged-rename|staged-retire|staged-redirect|staged-preparation|staged-payload|staged-return|staged-fetch-address|staged-fetch-control|staged-recovery-control|staged-execute-select|staged-frontend-select] " +
            "[uart-baud] [cache-ways] " +
            "[issue-width:2|4] [instruction-prefetch:0|1] [isa:rv64imac|rv64imafc|rv64gc] " +
            "[peripheral-clock-hz:0=same-domain]")
    require(args.lift(7).forall(Set("0", "1").contains), "instruction-prefetch must be 0 or 1")
    val output = Path.of(args(0)).toAbsolutePath
    val clockHz = if (args.length >= 2) args(1).toInt else 40000000
    Files.createDirectories(output)
    ChiselStage.emitSystemVerilogFile(new BoardSocTop(socClockHz = clockHz, externalDdr = args.lift(2).contains("ddr"),
        timingProfile = args.lift(3).getOrElse(BoardSocConfig.timingProfile),
        uartBaud = args.lift(4).map(_.toInt).getOrElse(1500000),
        dataCacheWays = args.lift(5).map(_.toInt).getOrElse(BoardSocConfig.dataCacheWays),
        issueWidth = args.lift(6).map(_.toInt).getOrElse(BoardSocConfig.issueWidth),
        instructionPrefetch = !args.lift(7).contains("0"),
        isaProfile = args.lift(8).getOrElse(BoardSocConfig.isaProfile),
        peripheralClockHz = args.lift(9).map(_.toInt).getOrElse(0)),
        Array("--target-dir", output.toString),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
