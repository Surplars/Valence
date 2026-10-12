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
    val allowed = Set("--rob-entries=16", "--rob-entries=32", "--rob-entries=64",
            "--registered-pmp-regions", "--published-pmp-changes", "--ddr-write-collection-flow",
            "--line-transfer-dispatch-flow", "--internal-line-grant", "--concurrent-read-store-prefetch", "--memory-schedule-overlap",
            "--line-read-channel", "--split-prefetch-tracking", "--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption", "--read-prefetch-store-hold",
            "--durable-read-prefetch-candidate", "--read-prefetch-behind-store",
            "--dtlb-write-read-reuse", "--translation-hit-flow", "--independent-demand-admission", "--dma-line-entries=8",
            "--ddr-outstanding=4", "--ddr-outstanding=8",
            "--ddr-write-credits=1", "--ddr-write-credits=2", "--ddr-write-credits=4",
            "--physical-regs=48", "--physical-regs=64", "--canonical-virtual-store-overlap", "--memory-proof-frontier", "--frozen-store-proof-transport", "--pending-virtual-store-proof", "--registered-pending-store-query", "--aligned-fetch-permission-stage", "--registered-canonical-store-event", "--shared-lane1-owner-match", "--shared-canonical-store-owner-match", "--local-payload-write-row", "--eager-fetch-prefix-select", "--direct-rank1-memory-source-ids", "--direct-registered-execution-operands", "--local-payload-write-enable", "--bound-head-store-overlap", "--pending-ready-store-bypass", "--tagged-store-returns", "--pending-virtual-store-proof-slots=1", "--pending-virtual-store-proof-slots=2", "--pending-store-early-load-credits=1", "--pending-store-early-load-credits=2", "--posted-prefetch-coexistence", "--posted-store-merge", "--posted-prefetch-head-offer", "--translated-response-empty-flow", "--store-prefetch-mru-insertion", "--store-prefetch-lru-victim", "--distinct-way-release", "--store-next-line-prefetch", "--prepared-store-lookahead", "--posted-preparation-priority", "--reconstruct-issue-token-index", "--shared-memory-address-state", "--data-translation-entries=4", "--data-translation-entries=8",
            "--data-translation-entries=16", "--data-translation-entries=32", "--fetch-previous-packet", "--load-order-older-retire", "--lsu-entries=2", "--lsu-entries=4", "--dma-line-entries=1", "--dma-line-entries=2", "--dma-line-entries=4", "--dma-line-yield-cycles=0", "--dma-line-yield-cycles=4", "--dma-line-yield-cycles=8", "--dma-line-yield-cycles=16", "--dma-line-yield-cycles=32", "--dma-line-yield-cycles=64", "--dma-line-transfers", "--prefetch-break-on-store", "--prefetch-candidate-cycles=1", "--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16", "--selected", "--share-protected-head-payload", "--banked-instruction-data", "--owner-local-issue-ready", "--shared-fetch-pmp-relations", "--experimental-trispeed-ethernet", "--independent-fetch-payload-capture", "--reference", "--candidate", "--virtual-ram-load-precheck", "--experimental-jtag-stub", "--experimental-jtag-ram", "--experimental-jtag-bscan=1", "--experimental-jtag-bscan=2", "--experimental-jtag-bscan=3", "--experimental-jtag-bscan=4", "--prechecked-data-flow", "--physical-load-ingress-flow")
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
