package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.FpgaNextConfig

/** Same fixed CPU/cache/fabric profile as the native export, without clock-domain peripherals. */
object FpgaNextBoardGsimMain extends App {
    val options = args.drop(1).toSet
    require(args.nonEmpty && options.size == args.length - 1 &&
        options.subsetOf(Set("--prefetch-break-on-store", "--prefetch-candidate-cycles=1", "--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16", "--selected", "--share-protected-head-payload", "--banked-instruction-data", "--owner-local-issue-ready", "--shared-fetch-pmp-relations", "--independent-fetch-payload-capture", "--reference", "--candidate", "--virtual-ram-load-precheck")) &&
        !(options.contains("--reference") && options.contains("--candidate")),
        "usage: FpgaNextBoardGsimMain output-directory [--reference|--candidate] [--virtual-ram-load-precheck]")
    val c = FpgaNextConfig.fromOptions(options, defaultSelected = false)
    ChiselStage.emitCHIRRTLFile(new BoardSocGsim(
        externalDdr = true, clockHz = c.cpuHz, timingProfile = c.timingProfile,
        uartBaud = c.uartBaud, dataCacheWays = c.cacheWays, issueWidth = c.issueWidth,
        instructionPrefetch = c.instructionPrefetch, isaProfile = c.isaProfile,
        ddrMemoryBytes = c.ddrBytes, frontendProbes = true, backendProbes = true,
        instructionLineCacheLines = c.instructionCacheLines,
        dataCacheLines = c.dataCacheLines, ddrBridge = c.ddr, cacheConcurrency = c.cache,
        loadIssueForwarding = c.loadIssueForwarding, tagConfig = c.tags,
        identityDataFlow = c.identityDataFlow, fpgaStorage = c.storage,
        virtualRamLoadPrecheck = c.virtualRamLoadPrecheck, floatingPointResources = c.floatingPointResources,
        independentFetchPayloadCapture = c.independentFetchPayloadCapture,
        ownerLocalIssueReady = c.ownerLocalIssueReady, sharedFetchPmpRelations = c.sharedFetchPmpRelations,
        bankedInstructionData = c.bankedInstructionData), Array("--target-dir", args(0)))
}
