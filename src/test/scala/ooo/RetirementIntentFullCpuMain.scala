package ooo
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.FpgaNextConfig
/** Exact current generic matching-board construction; no added DUT observers. */
object RetirementIntentFullCpuMain extends App {
    require(args.length > 1)
    val options = args.drop(1).toSeq
    FpgaNextProfileOptions.validate(options)
    require(options == RetirementIntentCpuProfile.defaultOptions || options == RetirementIntentCpuProfile.candidateOptions)
    val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    RetirementIntentCpuProfile.requireExact(c)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh output directory required")
    PostedBoardConfiguration.write(c, out.toString)
    Files.writeString(out.resolve("options.txt"), options.mkString("", "\n", "\n"))
    Files.writeString(out.resolve("assembly-contract.json"), """{"bscanChain":2,"clockManagement":true,"ethernetControl":true,"ethernetDma":true,"externalUart":true,"jtagRamDownload":true,"nativeTop":"FpgaNextSocTop","physicalQualification":false,"physicalTop":"soc_top_fpga_next_ddr","standaloneExternalDmi":false,"standaloneJtagEnabled":false,"triSpeedEthernet":true,"triSpeedTxFrameSlots":2}""" + "\n")
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true), Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
}
