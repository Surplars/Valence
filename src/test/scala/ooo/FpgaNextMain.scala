package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo.{FpgaNextConfig, FpgaNextSocTop}
import soc.ip.debug.JtagDebugParams

/** Fixed-profile FPGA-next export. No positional configuration can silently drift. */
object FpgaNextMain extends App {
    val options = args.drop(1).toSet
    require(args.nonEmpty && options.size == args.length - 1 &&
        options.subsetOf(Set("--rob-entries=16", "--rob-entries=32", "--rob-entries=64",
            "--registered-pmp-regions", "--published-pmp-changes", "--ddr-write-collection-flow",
            "--line-transfer-dispatch-flow", "--internal-line-grant", "--concurrent-read-store-prefetch", "--memory-schedule-overlap", "--future-home-way-reservation",
            "--line-read-channel", "--split-prefetch-tracking", "--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption", "--read-prefetch-store-hold",
            "--durable-read-prefetch-candidate", "--read-prefetch-behind-store",
            "--dtlb-write-read-reuse", "--translation-hit-flow", "--independent-demand-admission", "--dma-line-entries=8",
            "--ddr-outstanding=4", "--ddr-outstanding=8",
            "--ddr-write-credits=1", "--ddr-write-credits=2", "--ddr-write-credits=4",
            "--physical-regs=48", "--physical-regs=64", "--canonical-virtual-store-overlap", "--memory-proof-frontier", "--frozen-store-proof-transport", "--pending-virtual-store-proof", "--registered-pending-store-query", "--aligned-fetch-permission-stage", "--registered-canonical-store-event", "--shared-lane1-owner-match", "--direct-rank1-memory-source-ids", "--direct-registered-execution-operands", "--local-payload-write-enable", "--shared-canonical-store-owner-match", "--local-payload-write-row", "--eager-fetch-prefix-select", "--bound-head-store-overlap", "--pending-ready-store-bypass", "--tagged-store-returns", "--pending-virtual-store-proof-slots=1", "--pending-virtual-store-proof-slots=2", "--pending-store-early-load-credits=1", "--pending-store-early-load-credits=2", "--posted-prefetch-coexistence", "--posted-store-merge", "--posted-prefetch-head-offer", "--translated-response-empty-flow", "--store-prefetch-mru-insertion", "--store-prefetch-lru-victim", "--distinct-way-release", "--store-next-line-prefetch", "--prepared-store-lookahead", "--posted-preparation-priority", "--reconstruct-issue-token-index", "--shared-memory-address-state", "--data-translation-entries=4", "--data-translation-entries=8",
            "--data-translation-entries=16", "--data-translation-entries=32", "--fetch-previous-packet", "--load-order-older-retire", "--lsu-entries=2", "--lsu-entries=4", "--dma-line-entries=1", "--dma-line-entries=2", "--dma-line-entries=4", "--dma-line-yield-cycles=0", "--dma-line-yield-cycles=4", "--dma-line-yield-cycles=8", "--dma-line-yield-cycles=16", "--dma-line-yield-cycles=32", "--dma-line-yield-cycles=64", "--dma-line-transfers", "--prefetch-break-on-store", "--prefetch-candidate-cycles=1", "--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16", "--selected", "--share-protected-head-payload", "--banked-instruction-data", "--owner-local-issue-ready", "--shared-fetch-pmp-relations", "--experimental-trispeed-ethernet", "--independent-fetch-payload-capture", "--reference", "--candidate", "--virtual-ram-load-precheck", "--experimental-jtag-stub", "--experimental-jtag-ram", "--experimental-jtag-bscan=1", "--experimental-jtag-bscan=2", "--experimental-jtag-bscan=3", "--experimental-jtag-bscan=4", "--prechecked-data-flow", "--physical-load-ingress-flow")) &&
        !(options.contains("--reference") && options.contains("--candidate")),
        "usage: FpgaNextMain fresh-output-directory [--reference|--candidate] [--rob-entries=16|32|64] [--physical-regs=48|64] [--virtual-ram-load-precheck] [--prechecked-data-flow] [--physical-load-ingress-flow] [--fetch-previous-packet] [--data-translation-entries=4|8|16|32] [--prepared-store-lookahead] [--posted-preparation-priority] [--reconstruct-issue-token-index] [--shared-memory-address-state] [--store-next-line-prefetch] [--split-prefetch-tracking] [--read-prefetch-dirty-retry] [--read-prefetch-demand-adoption] [--read-prefetch-store-hold] [--durable-read-prefetch-candidate] [--read-prefetch-behind-store] [--registered-pmp-regions] [--published-pmp-changes] [--store-prefetch-mru-insertion] [--store-prefetch-lru-victim] [--distinct-way-release] [--translated-response-empty-flow] [--posted-store-merge] [--posted-prefetch-coexistence] [--posted-prefetch-head-offer] [--canonical-virtual-store-overlap] [--memory-proof-frontier]")
    val bscanOptions = options.filter(_.startsWith("--experimental-jtag-bscan="))
    require(bscanOptions.size <= 1, "Select exactly one allocated BSCAN chain")
    val bscanChain = bscanOptions.headOption.map(_.split("=")(1).toInt).getOrElse(0)
    val config = FpgaNextConfig.fromOptions(options, defaultSelected = true)
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "FPGA-next export requires a fresh directory")
    Files.createDirectories(output)
    var actualTiming: Option[Map[String, Any]] = None
    var actualEagerPrefix: Option[Map[String, Any]] = None
    var actualOwnerRow: Option[Map[String, Any]] = None
    PostedBoardConfiguration.write(config, output.toString)
    ChiselStage.emitSystemVerilogFile({
        val dut = new FpgaNextSocTop(config,
            JtagDebugParams(enabled = options.contains("--experimental-jtag-stub") || options.contains("--experimental-jtag-ram"),
                externalDmi = options.contains("--experimental-jtag-ram")), bscanChain = bscanChain)
        actualTiming = Some(TimingBatchActualAudit.capture(dut.board.platform, config))
        actualEagerPrefix = Some(EagerPrefixActualAudit.capture(dut.board.platform, config))
        actualOwnerRow = Some(OwnerRowActualAudit.capture(dut.board.platform, config))
        FutureHomeActualAudit.capture(dut.board.platform, config)
        dut
    },
        Array("--target-dir", output.toString),
        Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
    TimingBatchActualAudit.write(actualTiming.get, output.toString)
    EagerPrefixActualAudit.write(actualEagerPrefix.get, output.toString)
    OwnerRowActualAudit.write(actualOwnerRow.get, output.toString)
}
