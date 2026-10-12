package ooo

import soc.core.ooo._

/** Published ABC profile; only the five already-qualified short-host exceptions differ. */
object Lane1OwnerBackendProfile {
    val frozenOptions = Set(
        "--selected",
        "--data-translation-entries=16",
        "--registered-pmp-regions",
        "--experimental-trispeed-ethernet",
        "--experimental-jtag-bscan=2",
        "--dma-line-transfers",
        "--dma-line-entries=4",
        "--prefetch-candidate-cycles=16",
        "--virtual-ram-load-precheck",
        "--lsu-entries=4",
        "--physical-load-ingress-flow",
        "--ddr-write-collection-flow",
        "--line-transfer-dispatch-flow",
        "--line-read-channel",
        "--dtlb-write-read-reuse",
        "--translation-hit-flow",
        "--independent-demand-admission",
        "--split-prefetch-tracking",
        "--read-prefetch-dirty-retry",
        "--read-prefetch-demand-adoption",
        "--load-order-older-retire",
        "--fetch-previous-packet",
        "--prepared-store-lookahead",
        "--store-next-line-prefetch",
        "--store-prefetch-mru-insertion",
        "--posted-store-merge",
        "--posted-prefetch-coexistence",
        "--posted-prefetch-head-offer",
        "--canonical-virtual-store-overlap",
        "--published-pmp-changes",
        "--frozen-store-proof-transport",
        "--pending-virtual-store-proof",
        "--pending-virtual-store-proof-slots=2",
        "--bound-head-store-overlap",
        "--read-prefetch-store-hold",
        "--pending-ready-store-bypass",
        "--durable-read-prefetch-candidate",
        "--read-prefetch-behind-store",
        "--pending-store-early-load-credits=2",
        "--tagged-store-returns",
        "--internal-line-grant",
        "--concurrent-read-store-prefetch",
        "--memory-schedule-overlap",
        "--registered-pending-store-query",
        "--registered-canonical-store-event",
        "--aligned-fetch-permission-stage")
    val abc: OooParams = FpgaNextConfig.fromOptions(frozenOptions, defaultSelected = true).coreParams
    def params(shared: Boolean): OooParams = abc.copy(
        // The unchanged host supplies a small RAM and an untagged direct physical link.
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        taggedStoreReturns = false, postedStoreMerge = false, postedPrefetchHeadOffer = false,
        sharedLane1OwnerMatch = shared)
}
