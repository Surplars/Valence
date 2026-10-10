package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.FpgaNextConfig

/** Explicit profiles for separate experiments. Historical posted OFF/ON keeps its meaning. */
object PostedPrefetchBoardProfiles {
    private val baseOptions = Set("--selected", "--data-translation-entries=16", "--dma-line-transfers",
        "--dma-line-entries=4", "--virtual-ram-load-precheck", "--lsu-entries=4",
        "--physical-load-ingress-flow", "--load-order-older-retire", "--fetch-previous-packet",
        "--prepared-store-lookahead", "--store-next-line-prefetch", "--store-prefetch-mru-insertion")

    def options(experiment: String, mode: String): Set[String] = {
        require(Set("posted", "coexistence", "head-offer").contains(experiment), "unknown Board experiment")
        require(Set("off", "on").contains(mode), "explicit on/off required")
        baseOptions ++
            (if (experiment != "posted" || mode == "on") Set("--posted-store-merge") else Set.empty[String]) ++
            (if (experiment == "head-offer" || (experiment == "coexistence" && mode == "on"))
                Set("--posted-prefetch-coexistence") else Set.empty[String]) ++
            (if (experiment == "head-offer" && mode == "on") Set("--posted-prefetch-head-offer")
             else Set.empty[String])
    }

    def profile(experiment: String, mode: String): FpgaNextConfig = {
        val result = FpgaNextConfig.fromOptions(options(experiment, mode), defaultSelected = false)
        val expected = FpgaNextConfig.Selected.copy(dataTranslationEntries = 16,
            virtualRamLoadPrecheck = true, preparedStoreLookahead = true,
            storeNextLinePrefetch = true, storePrefetchMruInsertion = true,
            dmaLineTransfers = true, dmaLineEntries = 4,
            lsuEntries = 4, physicalLoadIngressFlow = true, loadOrderOlderRetire = true,
            fetchPreviousPacket = true, postedStoreMerge = experiment != "posted" || mode == "on",
            postedPrefetchCoexistence = experiment == "head-offer" || (experiment == "coexistence" && mode == "on"),
            postedPrefetchHeadOffer = experiment == "head-offer" && mode == "on")
        require(result == expected && result.coreParams == expected.coreParams,
            "explicit Board options differ from complete constructor profile")
        require(result.productArity == 31 && result.coreParams.productArity == 139,
            "Board constructor fields changed; review the complete frozen contract")
        result
    }

    def emit(experiment: String, args: Array[String]): Unit = {
        require(args.length == 2, "target directory and explicit on/off required")
        val selected = profile(experiment, args(1))
        PostedBoardConfiguration.write(selected, args(0))
        ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(selected, lineageProbes = true),
            Array("--target-dir", args(0)))
    }
}

object PostedPrefetchCoexistBoardGsimMain extends App {
    PostedPrefetchBoardProfiles.emit("coexistence", args)
}

object PostedPrefetchHeadOfferBoardGsimMain extends App {
    PostedPrefetchBoardProfiles.emit("head-offer", args)
}
