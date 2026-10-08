package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo.{BoardSocConfig, BoardSocTop, FpgaStorageConfig}

/** Export a board clock profile; blk_mem_gen_0 and XPM_MEMORY are supplied by Vivado. */
object BoardSocMain extends App {
    val virtualRamLoadPrecheck = args.contains("--virtual-ram-load-precheck")
    val boardArgs = args.filterNot(_ == "--virtual-ram-load-precheck")
    val (cli, fpgaStorage) = FpgaStorageConfig.parseArgs(boardArgs)
    require(cli.length >= 1 && cli.length <= 10,
        "usage: BoardSocMain output-directory [clock-hz] [ddr] " +
            "[baseline|early-issue|queued-memory|registered-response|registered-replay|staged-fabric|staged-control|staged-data|staged-execute|staged-rename|staged-retire|staged-redirect|staged-preparation|staged-payload|staged-return|staged-fetch-address|staged-fetch-control|staged-recovery-control|staged-execute-select|staged-frontend-select] " +
            "[uart-baud] [cache-ways] " +
            "[issue-width:2|4] [instruction-prefetch:0|1] [isa:rv64imac|rv64imafc|rv64gc] " +
            "[peripheral-clock-hz:0=same-domain] [--banked-rob] [--shared-store-reads] [--virtual-ram-load-precheck]")
    require(cli.lift(7).forall(Set("0", "1").contains), "instruction-prefetch must be 0 or 1")
    val output = Path.of(cli(0)).toAbsolutePath
    val clockHz = if (cli.length >= 2) cli(1).toInt else 40000000
    Files.createDirectories(output)
    ChiselStage.emitSystemVerilogFile(new BoardSocTop(socClockHz = clockHz, externalDdr = cli.lift(2).contains("ddr"),
        timingProfile = cli.lift(3).getOrElse(BoardSocConfig.timingProfile),
        uartBaud = cli.lift(4).map(_.toInt).getOrElse(1500000),
        dataCacheWays = cli.lift(5).map(_.toInt).getOrElse(BoardSocConfig.dataCacheWays),
        issueWidth = cli.lift(6).map(_.toInt).getOrElse(BoardSocConfig.issueWidth),
        instructionPrefetch = !cli.lift(7).contains("0"),
        isaProfile = cli.lift(8).getOrElse(BoardSocConfig.isaProfile),
        peripheralClockHz = cli.lift(9).map(_.toInt).getOrElse(0), fpgaStorage = fpgaStorage,
        virtualRamLoadPrecheck = virtualRamLoadPrecheck),
        Array("--target-dir", output.toString),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
