package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Actual ordinary native production top, with two independent state-reuse flags. */
object MemoryStateReuseNativeProfiles {
    def options(reconstruct: Boolean, shared: Boolean): Set[String] =
        StorePrefetchLruVictimProfiles.options(true) ++ Set("--posted-preparation-priority") ++
            (if (reconstruct) Set("--reconstruct-issue-token-index") else Set.empty[String]) ++
            (if (shared) Set("--shared-memory-address-state") else Set.empty[String])

    def profile(reconstruct: Boolean, shared: Boolean): FpgaNextConfig = {
        val baseline = StorePrefetchLruVictimProfiles.profile(true).copy(postedPreparationPriority = true)
        val selected = FpgaNextConfig.fromOptions(options(reconstruct, shared), defaultSelected = false)
        require(selected == baseline.copy(reconstructIssueTokenIndex = reconstruct, sharedMemoryAddressState = shared))
        require(selected.productArity == 58 && !selected.taggedStoreReturns && !selected.pendingReadyStoreBypass && !selected.boundHeadStoreOverlap && !selected.pendingVirtualStoreProof && !selected.frozenStoreProofTransport && selected.pendingVirtualStoreProofSlots == 1 && selected.pendingStoreEarlyLoadCredits == 1 && !selected.publishedPmpChanges && !selected.registeredPmpRegions && !selected.coreParams.registeredPmpRegions &&
            !selected.readPrefetchDemandAdoption && !selected.cache.readPrefetchDemandAdoption &&
            !selected.readPrefetchDirtyRetry && !selected.cache.readPrefetchDirtyRetry &&
            !selected.splitPrefetchTracking && !selected.cache.splitPrefetchTracking &&
            !selected.translationHitFlow && selected.ddrOutstanding == 4 && selected.ddrWriteCredits == 2 &&
            !selected.dataTlbWriteReadReuse && !selected.ddrWriteCollectionFlow &&
            !selected.lineTransferDispatchFlow && !selected.lineReadChannel && selected.coreParams.productArity == 151 && !selected.coreParams.taggedStoreReturns && !selected.coreParams.pendingReadyStoreBypass && !selected.coreParams.boundHeadStoreOverlap && !selected.coreParams.pendingVirtualStoreProof && !selected.coreParams.frozenStoreProofTransport && selected.coreParams.pendingVirtualStoreProofSlots == 1 && selected.coreParams.pendingStoreEarlyLoadCredits == 1 && !selected.coreParams.publishedPmpChanges &&
            !selected.distinctWayRelease && !selected.cache.distinctWayRelease)
        require(selected.coreParams == baseline.coreParams.copy(
            reconstructIssueTokenIndex = reconstruct, sharedMemoryAddressState = shared))
        require(selected.cache == baseline.cache && selected.ddr == baseline.ddr &&
            selected.tags == baseline.tags && selected.storage == baseline.storage.copy(
                reconstructIssueTokenIndex = reconstruct, sharedMemoryAddressState = shared) &&
            selected.network == baseline.network && selected.floatingPointResources == baseline.floatingPointResources)
        require(selected.memoryProofFrontier && selected.storePrefetchLruVictim && selected.postedPreparationPriority)
        selected
    }
}

object MemoryStateReuseNativeMain extends App {
    require(args.length == 3 && args.drop(1).forall(Set("off", "on").contains),
        "fresh-output-directory and explicit index off|on, address off|on required")
    require(!Files.exists(Paths.get(args(0))), "memory state native audit requires a fresh directory")
    val reconstruct = args(1) == "on"
    val shared = args(2) == "on"
    val profile = MemoryStateReuseNativeProfiles.profile(reconstruct, shared)
    PostedBoardConfiguration.write(profile, args(0))
    new CanonicalVirtualStoreActualParamsAudit(profile, args(0), "on",
        MemoryStateReuseNativeProfiles.options(reconstruct, shared), "memory-state-reuse-" + args.drop(1).mkString("-"))
}
