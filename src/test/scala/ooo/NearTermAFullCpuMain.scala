package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo.FpgaNextConfig

/** Exactly one explicit ON service-envelope emitter; no implicit OFF branch. */
object NearTermAFullCpuMain extends App {
    require(args.length == 69, "usage: NearTermAFullCpuMain fresh-directory exact-68-native-options")
    val options = args.drop(1).toSeq
    val c = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    NearTermAProfile.requireOn(options, c)
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh output directory required")
    PostedBoardConfiguration.write(c, out.toString)
    Files.writeString(out.resolve("options.txt"), options.mkString("", "\n", "\n"))
    // Keep the retained assembly provenance literal. The current source bridge
    // is a separate metadata record and does not imply physical qualification.
    Files.writeString(out.resolve("assembly-contract.json"),
        """{"bscanChain":2,"physicalComparisonResetMode":"T1","physicalComparisonCommit":"b1bb5d863f7ad5b034f148b18968d19e46ace75b","publishedSourceBaseCommit":"9937714cee13e26e54b8aabc4d149585af22245b","sourceBaseTree":"ee12ce97f959dc87934e6ebb462608867c81a653","qualificationInherited":false,"clockManagement":true,"ethernetControl":true,"ethernetDma":true,"externalUart":true,"jtagRamDownload":true,"nativeTop":"FpgaNextSocTop","physicalQualification":false,"physicalTop":"soc_top_fpga_next_ddr","standaloneExternalDmi":false,"standaloneJtagEnabled":false,"triSpeedEthernet":true,"triSpeedTxFrameSlots":2}""" + "\n")
    Files.writeString(out.resolve("near-term-a-source-bridge.json"),
        PostedBoardConfiguration.json(NearTermAProfile.sourceBridge) + "\n")
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c, verifyConfiguration = true),
        Array("--target-dir", out.toString))
    MatchingFabricAudit.write(out.toString)
}
