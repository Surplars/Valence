package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo._

import soc.ip.dma.NetworkDmaConfig

object EthernetTimingMain extends App {
    val (memoryArgs, mixedMemory) = soc.core.ooo.MixedMemoryConfig.parseArgs(args)
    val (storageArgs, fpgaStorage) = FpgaStorageConfig.parseArgs(memoryArgs)
    val identityDataFlow = storageArgs.contains("--identity-data-flow")
    val tagConfig = CacheTagConfig(compact = args.contains("--compact-tags"))
    val (cli, networkConfig) = NetworkDmaConfig.parseArgs(storageArgs.filterNot(arg => arg == "--compact-tags" || arg == "--identity-data-flow"))
    require(cli.nonEmpty && cli.length <= 12,
        "usage: EthernetTimingMain output [isa] [board] [profile] [dma] [instruction-cache-lines] [data-cache-lines] [ddr-read-slots:1|2|4|8] [ddr-burst-beats:8|16] [read-mshrs:1|2|4] [cache-response-entries] [load-issue-forwarding:0|1] [--compact-tags] [--identity-data-flow] [--unordered-ddr-responses] [--data-next-line-prefetch] [--ddr-write-slots=N] [--cache-writebacks=N] [--overlap-writeback-refill] [--banked-rob] [--shared-store-reads] [--lvt-prf] [--network-{frame-bytes|mac-slots|rx-slots|memory-credits|tx-slots}=N]")
    require(cli.lift(11).forall(Set("0", "1").contains), "load issue forwarding must be 0 or 1")
    val output = Path.of(cli.head)
    require(!Files.exists(output), "fresh evidence directory required")
    val isa = cli.lift(1).getOrElse("rv64gc")
    val board = cli.lift(2).contains("board")
    require(board || !mixedMemory.specified, "mixed memory options require the board exporter")
    require(board || networkConfig == NetworkDmaConfig.Default, "network options require the board exporter")
    require(board || !fpgaStorage.enabled, "FPGA storage mapping requires the board exporter")
    require(board || !identityDataFlow, "identity data flow requires the board adapter exporter")
    require(board || !tagConfig.compact, "compact tags require a board/cache exporter")
    val profile = cli.lift(3).getOrElse("staged-ethernet")
    if (board) ChiselStage.emitSystemVerilogFile(new EthernetSocTop(isa, profile,
        packetDma = cli.lift(4).contains("dma"),
        instructionLineCacheLines = cli.lift(5).map(_.toInt).getOrElse(8),
        dataCacheLines = cli.lift(6).map(_.toInt).getOrElse(32),
        ddrBridge = mixedMemory.ddr(DdrBridgeConfig(maxOutstanding = cli.lift(7).map(_.toInt).getOrElse(1),
            maxBurstBeats = cli.lift(8).map(_.toInt).getOrElse(16))),
        cacheConcurrency = mixedMemory.cache(CoherentCacheConcurrency(readMshrs = cli.lift(9).map(_.toInt).getOrElse(1),
            responseEntries = cli.lift(10).map(_.toInt).getOrElse(2))),
        loadIssueForwarding = cli.lift(11).map(_ == "1"),
        tagConfig = tagConfig, networkDmaConfig = networkConfig, identityDataFlow = identityDataFlow, fpgaStorage = fpgaStorage),
        Array("--target-dir", output.toString), Array("--split-verilog", "-disable-all-randomization",
            "-strip-debug-info", "-default-layer-specialization=disable"))
    else ChiselStage.emitSystemVerilogFile(new MachineCore(
        BoardSocConfig.boardParams(profile, externalDdr = true, isa = isa,
            loadIssueForwarding = cli.lift(11).map(_ == "1"))),
        Array("--target-dir", output.toString), Array("--split-verilog", "-disable-all-randomization",
            "-strip-debug-info", "-default-layer-specialization=disable"))
}
