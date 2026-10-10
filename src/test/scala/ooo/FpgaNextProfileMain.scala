package ooo

import java.nio.file.{Files, Path}
import soc.core.ooo.FpgaNextConfig

/** Pure constructor report for the exact options expanded by export.py.
  * No hardware elaboration, simulation, or independent qualification claim.
  * Compare every reported field against a separately frozen qualified profile.
  */
object FpgaNextProfileMain extends App {
    require(args.nonEmpty, "usage: FpgaNextProfileMain fresh-output-directory [native export options]")
    val options = args.drop(1).toSet
    require(options.size == args.length - 1, "duplicate native export options")
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "configuration report requires a fresh directory")
    val config = FpgaNextConfig.fromOptions(options, defaultSelected = true)
    require(config.productArity == 27 && config.coreParams.productArity == 136,
        "configuration field count changed; review the complete qualified contract")
    PostedBoardConfiguration.write(config, output.toString)
}
