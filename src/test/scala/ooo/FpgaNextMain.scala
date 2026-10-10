package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo.{FpgaNextConfig, FpgaNextSocTop}
import soc.ip.debug.JtagDebugParams

/** Fixed-profile FPGA-next export. No positional configuration can silently drift. */
object FpgaNextMain extends App {
    val options = args.drop(1).toSet
    require(args.nonEmpty && options.size == args.length - 1 &&
        options.subsetOf(Set("--posted-store-merge", "--translated-response-empty-flow", "--store-prefetch-mru-insertion", "--store-next-line-prefetch", "--prepared-store-lookahead", "--data-translation-entries=4", "--data-translation-entries=8",
            "--data-translation-entries=16", "--data-translation-entries=32", "--fetch-previous-packet", "--load-order-older-retire", "--lsu-entries=2", "--lsu-entries=4", "--dma-line-entries=1", "--dma-line-entries=2", "--dma-line-entries=4", "--dma-line-yield-cycles=0", "--dma-line-yield-cycles=4", "--dma-line-yield-cycles=8", "--dma-line-yield-cycles=16", "--dma-line-yield-cycles=32", "--dma-line-yield-cycles=64", "--dma-line-transfers", "--prefetch-break-on-store", "--prefetch-candidate-cycles=1", "--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16", "--selected", "--share-protected-head-payload", "--banked-instruction-data", "--owner-local-issue-ready", "--shared-fetch-pmp-relations", "--experimental-trispeed-ethernet", "--independent-fetch-payload-capture", "--reference", "--candidate", "--virtual-ram-load-precheck", "--experimental-jtag-stub", "--experimental-jtag-ram", "--experimental-jtag-bscan=1", "--experimental-jtag-bscan=2", "--experimental-jtag-bscan=3", "--experimental-jtag-bscan=4", "--prechecked-data-flow", "--physical-load-ingress-flow")) &&
        !(options.contains("--reference") && options.contains("--candidate")),
        "usage: FpgaNextMain fresh-output-directory [--reference|--candidate] [--virtual-ram-load-precheck] [--prechecked-data-flow] [--physical-load-ingress-flow] [--fetch-previous-packet] [--data-translation-entries=4|8|16|32] [--prepared-store-lookahead] [--store-next-line-prefetch] [--store-prefetch-mru-insertion] [--translated-response-empty-flow] [--posted-store-merge]")
    val bscanOptions = options.filter(_.startsWith("--experimental-jtag-bscan="))
    require(bscanOptions.size <= 1, "Select exactly one allocated BSCAN chain")
    val bscanChain = bscanOptions.headOption.map(_.split("=")(1).toInt).getOrElse(0)
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "FPGA-next export requires a fresh directory")
    Files.createDirectories(output)
    val config = FpgaNextConfig.fromOptions(options, defaultSelected = true)
    ChiselStage.emitSystemVerilogFile(new FpgaNextSocTop(config,
        JtagDebugParams(enabled = options.contains("--experimental-jtag-stub") || options.contains("--experimental-jtag-ram"),
            externalDmi = options.contains("--experimental-jtag-ram")), bscanChain = bscanChain),
        Array("--target-dir", output.toString),
        Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
}
