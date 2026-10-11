package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.FpgaNextConfig

/** Executing production two-issue CPU, MMU, caches and external DDR assembly.
  * Only bandwidth policies vary; no ROB/PRF/LSU/TLB/cache/DDR capacity sweep.
  */
object CpuSv39BandwidthGsimMain extends App {
    require(args.length == 2 && Set("baseline", "reuse", "batch", "flow", "scheduled", "accepted", "admission",
        "admission-retained").contains(args(1)),
        "output directory and baseline|reuse|batch|flow|scheduled|accepted|admission|admission-retained required")
    val scheduled = args(1) == "scheduled"
    val admission = args(1) == "admission" || args(1) == "admission-retained"
    val retained = args(1) == "flow" || scheduled || args(1) == "admission-retained"
    val flow = retained || args(1) == "accepted" || admission
    val batch = args(1) == "batch" || flow
    val profile = FpgaNextConfig.Selected.copy(
        virtualRamLoadPrecheck = true, physicalLoadIngressFlow = true,
        canonicalVirtualStoreOverlap = true, fetchPreviousPacket = true,
        preparedStoreLookahead = true, postedStoreMerge = true,
        postedPrefetchCoexistence = true, postedPrefetchHeadOffer = true,
        storeNextLinePrefetch = true, storePrefetchMruInsertion = true,
        dataTlbWriteReadReuse = args(1) != "baseline",
        translationHitFlow = flow, distinctWayRelease = scheduled,
        prefetchCandidateCycles = if (retained) 16 else 1,
        ddrWriteCollectionFlow = batch, lineTransferDispatchFlow = batch,
        lineReadChannel = batch, independentDemandAdmission = admission)
    require(profile.issueWidth == 2 && profile.lsuEntries == 2 &&
        profile.dataTranslationEntries == 8 && profile.ddrOutstanding == 4 && profile.ddrWriteCredits == 2)
    PostedBoardConfiguration.write(profile, args(0))
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(profile), Array("--target-dir", args(0)))
}
