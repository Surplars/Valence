package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo.{FpgaNextConfig, FpgaNextSocTop}
import soc.ip.debug.JtagDebugParams

/** Fixed-profile FPGA-next export. No positional configuration can silently drift. */
object FpgaNextMain extends App {
    require(args.nonEmpty, "supply an output directory and exact native export options")
    FpgaNextProfileOptions.validate(args.drop(1).toSeq)
    val options = args.drop(1).toSet
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
    var actualHeadDrain: Option[Map[String, Any]] = None
    var actualPlacedTiming: Option[Map[String, Any]] = None
    var actualRetirementIntent: Option[Map[String, Any]] = None
    PostedBoardConfiguration.write(config, output.toString)
    ChiselStage.emitSystemVerilogFile({
        val dut = new FpgaNextSocTop(config,
            JtagDebugParams(enabled = options.contains("--experimental-jtag-stub") || options.contains("--experimental-jtag-ram"),
                externalDmi = options.contains("--experimental-jtag-ram")), bscanChain = bscanChain)
        actualTiming = Some(TimingBatchActualAudit.capture(dut.board.platform, config))
        actualEagerPrefix = Some(EagerPrefixActualAudit.capture(dut.board.platform, config))
        actualOwnerRow = Some(OwnerRowActualAudit.capture(dut.board.platform, config))
        FutureHomeActualAudit.capture(dut.board.platform, config)
        actualHeadDrain = Some(HeadDrainActualAudit.capture(dut.board.platform, config))
        actualRetirementIntent = Some(RetirementIntentActualAudit.capture(dut.board.platform, config))
        actualPlacedTiming = Some(PlacedTimingActualAudit.capture(dut.board.platform, config))
        dut
    },
        Array("--target-dir", output.toString),
        Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
    TimingBatchActualAudit.write(actualTiming.get, output.toString)
    EagerPrefixActualAudit.write(actualEagerPrefix.get, output.toString)
    OwnerRowActualAudit.write(actualOwnerRow.get, output.toString)
    HeadDrainActualAudit.write(actualHeadDrain.get, output.toString)
    PlacedTimingActualAudit.write(actualPlacedTiming.get, output.toString)
    Files.writeString(output.resolve("actual-retirement-intent.json"),
        PostedBoardConfiguration.json(actualRetirementIntent.get) + "\n")
}
