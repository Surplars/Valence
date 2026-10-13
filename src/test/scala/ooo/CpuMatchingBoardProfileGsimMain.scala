package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.{FpgaNextConfig, BoardSocConfig}

/** Full-population CPU/fabric target; native physical services are explicit models.
  * The target assembly JSON is not evidence that BSCAN/CDC primitives are simulated.
  */
object CpuMatchingBoardProfileGsimMain extends App {
    require(args.length > 1, "output-directory plus explicit complete board-profile options required")
    val options = args.drop(1).toSet
    val allowed = FpgaNextProfileOptions.allowed
    require(options.size == args.length - 1 && options.subsetOf(allowed), "unknown/duplicate board profile option")
    require(options.count(Set("--selected", "--reference", "--candidate").contains) == 1,
        "board profile must explicitly select one topology; no entrypoint default")
    require(options.contains("--experimental-trispeed-ethernet") &&
        options.filter(_.startsWith("--experimental-jtag")) == Set("--experimental-jtag-bscan=2"),
        "the matching target assembly requires tri-speed and allocated-candidate BSCAN2 RAM download")
    val c = FpgaNextConfig.fromOptions(options, defaultSelected = false)
    require(c.lsuEntries == 4 && c.timingProfile == BoardSocConfig.memoryCapacityProfile,
        "current board pair retains all four LSU owners and their actual occupancy view")
    val out = Paths.get(args(0))
    require(!Files.exists(out.resolve("profile.json")) && !Files.exists(out.resolve("BoardSocGsim.fir")), "fresh board model output required")
    PostedBoardConfiguration.write(c, args(0))
    Files.writeString(out.resolve("options.txt"), args.drop(1).mkString("\n") + "\n")
    Files.writeString(out.resolve("assembly-contract.json"), """{"bscanChain":2,"clockManagement":true,"ethernetControl":true,"ethernetDma":true,"externalUart":true,"jtagRamDownload":true,"nativeTop":"FpgaNextSocTop","physicalQualification":false,"physicalTop":"soc_top_fpga_next_ddr","standaloneExternalDmi":false,"standaloneJtagEnabled":false,"triSpeedEthernet":true,"triSpeedTxFrameSlots":2}""" + "\n")
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true), Array("--target-dir", args(0)))
    MatchingFabricAudit.write(args(0))
}
