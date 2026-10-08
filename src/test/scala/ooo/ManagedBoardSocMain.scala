package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.{BoardSocTop, DdrBridgeConfig, CoherentCacheConcurrency, CacheTagConfig, FpgaStorageConfig}

/** Opt-in native GMII/CMU/UART board candidate. Requires an external RGMII
  * adapter, fixed raw clocks and common reset; not a replacement old bit top.
  */
import soc.ip.dma.NetworkDmaConfig

object ManagedBoardSocMain extends App {
    val virtualRamLoadPrecheck = args.contains("--virtual-ram-load-precheck")
    val boardArgs = args.filterNot(_ == "--virtual-ram-load-precheck")
    val (memoryArgs, mixedMemory) = soc.core.ooo.MixedMemoryConfig.parseArgs(boardArgs)
    val (storageArgs, fpgaStorage) = FpgaStorageConfig.parseArgs(memoryArgs)
    val identityDataFlow = storageArgs.contains("--identity-data-flow")
    val tagConfig = CacheTagConfig(compact = args.contains("--compact-tags"))
    val (cli, networkConfig) = NetworkDmaConfig.parseArgs(storageArgs.filterNot(arg => arg == "--compact-tags" || arg == "--identity-data-flow"))
    require(cli.nonEmpty && cli.length <= 16,
        "usage: ManagedBoardSocMain output [cpu-hz] [profile] [baud] [isa] [aon-hz] [uart-hz] [ddr-ui-hz] [ddr-bytes] [instruction-cache-lines] [data-cache-lines] [ddr-read-slots:1|2|4|8] [ddr-burst-beats:8|16] [read-mshrs:1|2|4] [cache-response-entries] [load-issue-forwarding:0|1] [--compact-tags] [--identity-data-flow] [--unordered-ddr-responses] [--data-next-line-prefetch] [--ddr-write-slots=N] [--cache-writebacks=N] [--overlap-writeback-refill] [--banked-rob] [--shared-store-reads] [--lvt-prf] [--virtual-ram-load-precheck] [--network-{frame-bytes|mac-slots|rx-slots|memory-credits|tx-slots}=N]")
    require(cli.lift(15).forall(Set("0", "1").contains), "load issue forwarding must be 0 or 1")
    ChiselStage.emitSystemVerilogFile(new BoardSocTop(
        socClockHz = cli.lift(1).map(_.toInt).getOrElse(100000000),
        externalDdr = true,
        timingProfile = cli.lift(2).getOrElse("staged-fetch-feedback"),
        uartBaud = cli.lift(3).map(_.toInt).getOrElse(460800),
        isaProfile = cli.lift(4).getOrElse("rv64imac"),
        issueWidth = 2,
        peripheralClockHz = cli.lift(6).map(_.toInt).getOrElse(50000000),
        clockManagementHz = cli.lift(5).map(_.toInt).getOrElse(50000000),
        ddrUiClockHz = cli.lift(7).map(_.toInt).getOrElse(250000000),
        ethernetControl = true, ethernetDma = true, managedPeripherals = true,
        ddrMemoryBytes = cli.lift(8).map(BigInt(_)).getOrElse(soc.core.ooo.BoardSocConfig.ddrBytes),
        instructionLineCacheLines = cli.lift(9).map(_.toInt).getOrElse(8),
        dataCacheLines = cli.lift(10).map(_.toInt).getOrElse(32),
        ddrBridge = mixedMemory.ddr(DdrBridgeConfig(maxOutstanding = cli.lift(11).map(_.toInt).getOrElse(1),
            maxBurstBeats = cli.lift(12).map(_.toInt).getOrElse(16))),
        cacheConcurrency = mixedMemory.cache(CoherentCacheConcurrency(readMshrs = cli.lift(13).map(_.toInt).getOrElse(1),
            responseEntries = cli.lift(14).map(_.toInt).getOrElse(2))),
        loadIssueForwarding = cli.lift(15).map(_ == "1"),
        tagConfig = tagConfig, networkDmaConfig = networkConfig, identityDataFlow = identityDataFlow, fpgaStorage = fpgaStorage,
        virtualRamLoadPrecheck = virtualRamLoadPrecheck),
        Array("--target-dir", cli.head),
        Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
}
