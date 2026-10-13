package ooo

import soc.core.ooo._

/** Explicit 59+5 experiment; historical option vectors and presets stay intact. */
private[ooo] object R3ReadLocalityProfile {
    val baseCommit = "785e3db558fb594816cc65e9e244e0a97eb282bd"
    val fields = Seq("fetchReadyDataClear", "memoryPreparationHeadMask", "directRank0MemorySourceIds",
        "retirementSlotIdentity", "localCacheReadSelection")
    val additions = Seq("--fetch-ready-data-clear", "--memory-preparation-head-mask", "--direct-rank0-memory-source-ids",
        "--retirement-slot-identity", "--local-cache-read-selection")
    val oldOptions = PlacedTimingProfile.candidateOptions
    val onOptions = oldOptions ++ additions
    require(oldOptions.size == 59 && onOptions.size == 64 && onOptions.distinct.size == 64)
    FpgaNextProfileOptions.validate(onOptions)
    val off = FpgaNextConfig.fromOptions(oldOptions.toSet, defaultSelected = false)
    val on = FpgaNextConfig.fromOptions(onOptions.toSet, defaultSelected = false)
    require(on.copy(fetchReadyDataClear = false, memoryPreparationHeadMask = false,
        directRank0MemorySourceIds = false, retirementSlotIdentity = false, localCacheReadSelection = false) == off,
        "only the five named default-OFF fields may differ from retained59")
    require(on.coreParams.copy(fetchReadyDataClear = false, memoryPreparationHeadMask = false,
        directRank0MemorySourceIds = false, retirementSlotIdentity = false) == off.coreParams,
        "only the four named core fields may differ from retained59")
    require(on.cache == off.cache && on.ddr == off.ddr, "cache/DDR resource products must remain identical")
    for (c <- Seq(off, on)) {
        PlacedTimingProfileBridge.requireShape(c)
        require(c.productArity == 84 && c.coreParams.productArity == 168 &&
            c.cache.productArity == 23 && c.ddr.productArity == 9)
    }
    def requireOn(options: Seq[String], c: FpgaNextConfig): Unit = {
        FpgaNextProfileOptions.validate(options)
        require(options == onOptions, "exact ordered retained59 plus five ON options required")
        require(c == on, "complete ON constructor differs")
    }
    val sourceBridge = Map("schema" -> "r3-read-locality-source-bridge-v1",
        "publishedSourceBaseCommit" -> baseCommit, "retainedModelOptions" -> 59,
        "candidateOptions" -> 64, "newDefaultOffFields" -> fields,
        "qualificationInherited" -> false, "physicalQualification" -> false)
}
