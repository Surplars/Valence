package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.{FpgaNextConfig, BoardSocConfig}

/** Exact board-profile argv; CPU/cache/translation/memory path, external DDR model.
  * Physical managed peripherals and independent clocks remain native-board qualification.
  */
object CpuBoardProfileGsimMain extends App {
    require(args.length > 1, "output-directory plus explicit complete board-profile options required")
    val options = args.drop(1).toSet
    val allowed = FpgaNextProfileOptions.allowed
    require(options.size == args.length - 1 && options.subsetOf(allowed), "unknown/duplicate board profile option")
    require(options.count(Set("--selected", "--reference", "--candidate").contains) == 1,
        "board profile must explicitly select one topology; no entrypoint default")
    require(!options.exists(_.startsWith("--experimental-jtag")) && !options.contains("--experimental-trispeed-ethernet"),
        "this CPU path requires the separately qualified JTAG-OFF fixed-gigabit board perimeter")
    val c = FpgaNextConfig.fromOptions(options, defaultSelected = false)
    require(c.lsuEntries == 4 && c.timingProfile == BoardSocConfig.memoryCapacityProfile,
        "current board pair retains all four LSU owners and their actual occupancy view")
    val out = Paths.get(args(0))
    require(!Files.exists(out.resolve("profile.json")) && !Files.exists(out.resolve("BoardSocGsim.fir")), "fresh board model output required")
    PostedBoardConfiguration.write(c, args(0))
    Files.writeString(out.resolve("options.txt"), args.drop(1).mkString("\n") + "\n")
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true), Array("--target-dir", args(0)))
}
