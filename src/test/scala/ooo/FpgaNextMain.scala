package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo.{FpgaNextConfig, FpgaNextSocTop}
import soc.ip.debug.JtagDebugParams

/** Fixed-profile FPGA-next export. No positional configuration can silently drift. */
object FpgaNextMain extends App {
    val options = args.drop(1).toSet
    require(args.nonEmpty && options.size == args.length - 1 &&
        options.subsetOf(Set("--prefetch-break-on-store", "--prefetch-candidate-cycles=1", "--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16", "--selected", "--share-protected-head-payload", "--banked-instruction-data", "--owner-local-issue-ready", "--shared-fetch-pmp-relations", "--experimental-trispeed-ethernet", "--independent-fetch-payload-capture", "--reference", "--candidate", "--virtual-ram-load-precheck", "--experimental-jtag-stub")) &&
        !(options.contains("--reference") && options.contains("--candidate")),
        "usage: FpgaNextMain fresh-output-directory [--reference|--candidate] [--virtual-ram-load-precheck]")
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "FPGA-next export requires a fresh directory")
    Files.createDirectories(output)
    val config = FpgaNextConfig.fromOptions(options, defaultSelected = true)
    ChiselStage.emitSystemVerilogFile(new FpgaNextSocTop(config,
        JtagDebugParams(enabled = options.contains("--experimental-jtag-stub"))),
        Array("--target-dir", output.toString),
        Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
}
