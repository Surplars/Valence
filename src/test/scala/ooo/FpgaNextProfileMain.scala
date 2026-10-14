package ooo

import java.nio.file.{Files, Path}
import soc.core.ooo.FpgaNextConfig

/** The constructor-only reporter accepts the exact native export option universe. */
private[ooo] object FpgaNextProfileOptions {
    val allowed: Set[String] = Set("--held-alu-issue-forwarding", "--tri-speed-raw-clock-handoff", "--rob-entries=16", "--rob-entries=32", "--rob-entries=64",
            "--posted-younger-load-seal-deferral", "--registered-pmp-regions", "--published-pmp-changes", "--ddr-write-collection-flow",
            "--line-transfer-dispatch-flow", "--internal-line-grant", "--concurrent-read-store-prefetch", "--memory-schedule-overlap", "--future-home-way-reservation",
            "--line-read-channel", "--local-payload-write-enable", "--split-prefetch-tracking", "--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption", "--read-prefetch-store-hold",
            "--durable-read-prefetch-candidate", "--read-prefetch-behind-store",
            "--dtlb-write-read-reuse", "--translation-hit-flow", "--independent-demand-admission", "--dma-line-entries=8",
            "--ddr-outstanding=4", "--ddr-outstanding=8",
            "--ddr-write-credits=1", "--ddr-write-credits=2", "--ddr-write-credits=4",
            "--physical-regs=48", "--physical-regs=64", "--canonical-virtual-store-overlap", "--memory-proof-frontier", "--frozen-store-proof-transport", "--pending-virtual-store-proof", "--registered-pending-store-query", "--aligned-fetch-permission-stage", "--registered-canonical-store-event", "--shared-lane1-owner-match", "--shared-canonical-store-owner-match", "--local-payload-write-row", "--eager-fetch-prefix-select", "--predecoded-head-drain", "--retirement-intent", "--fetch-address-before-pmp", "--queued-head-selection", "--aligned-next-line-pmp", "--register-probe-lookup", "--local-address-ranges", "--direct-rank1-memory-source-ids", "--memory-preparation-head-mask", "--direct-rank0-memory-source-ids", "--fetch-ready-data-clear", "--fetch-accepted-prefix-validation", "--aligned-fetch-single-page", "--factor-checked-next-allowed", "--local-tagged-response-ready", "--retirement-slot-identity", "--local-cache-read-selection", "--direct-registered-execution-operands", "--bound-head-store-overlap", "--pending-ready-store-bypass", "--tagged-store-returns", "--pending-virtual-store-proof-slots=1", "--pending-virtual-store-proof-slots=2", "--pending-store-early-load-credits=1", "--pending-store-early-load-credits=2", "--posted-prefetch-coexistence", "--posted-store-merge", "--posted-prefetch-head-offer", "--translated-response-empty-flow", "--store-prefetch-mru-insertion", "--store-prefetch-lru-victim", "--distinct-way-release", "--store-next-line-prefetch", "--prepared-store-lookahead", "--posted-preparation-priority", "--reconstruct-issue-token-index", "--shared-memory-address-state", "--data-translation-entries=4", "--data-translation-entries=8",
            "--data-translation-entries=16", "--data-translation-entries=32", "--fetch-previous-packet", "--load-order-older-retire", "--lsu-entries=2", "--lsu-entries=4", "--dma-line-entries=1", "--dma-line-entries=2", "--dma-line-entries=4", "--dma-line-yield-cycles=0", "--dma-line-yield-cycles=4", "--dma-line-yield-cycles=8", "--dma-line-yield-cycles=16", "--dma-line-yield-cycles=32", "--dma-line-yield-cycles=64", "--dma-line-transfers", "--prefetch-break-on-store", "--prefetch-candidate-cycles=1", "--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16", "--selected", "--share-protected-head-payload", "--banked-instruction-data", "--owner-local-issue-ready", "--shared-fetch-pmp-relations", "--experimental-trispeed-ethernet", "--independent-fetch-payload-capture", "--reference", "--candidate", "--virtual-ram-load-precheck", "--experimental-jtag-stub", "--experimental-jtag-ram", "--experimental-jtag-bscan=1", "--experimental-jtag-bscan=2", "--experimental-jtag-bscan=3", "--experimental-jtag-bscan=4", "--prechecked-data-flow", "--physical-load-ingress-flow")
    def validate(options: Seq[String]): Unit = {
        require(options.distinct.size == options.size, "duplicate native export options")
        require(options.toSet.subsetOf(allowed), "unknown or valued-Boolean native export option")
        require(!(options.contains("--reference") && options.contains("--candidate")),
            "reference and candidate selectors are mutually exclusive")
    }
}

/** Pure constructor report for the exact options expanded by export.py.
  * No hardware elaboration, simulation, or independent qualification claim.
  * Compare every reported field against a separately frozen qualified profile.
  */
object FpgaNextProfileMain extends App {
    require(args.nonEmpty, "usage: FpgaNextProfileMain fresh-output-directory [native export options]")
    FpgaNextProfileOptions.validate(args.drop(1).toSeq)
    val options = args.drop(1).toSet
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "configuration report requires a fresh directory")
    val config = FpgaNextConfig.fromOptions(options, defaultSelected = true)
    HeadDrainActualAudit.requireShape(config)
    PostedBoardConfiguration.write(config, output.toString)
}
