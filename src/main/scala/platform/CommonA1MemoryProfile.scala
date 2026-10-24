package soc.platform

import soc.core.ooo.FpgaNextConfig

/** Explicit CPU-private memory policies. A policy validates the actual final
  * configuration; it never overrides a separately supplied tile configuration.
  * This leaves the public Selected preset and common transport ABI unchanged.
  */
sealed abstract class CommonA1MemoryProfile(val name: String) {
    def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit
}

object CommonA1MemoryProfile {
    /** Four LSU owners hide checked-translation/return latency, not four L1
      * misses. The cache and common Home retain two miss owners. CPU responses
      * remain acceptance-ordered and carry no return handle across the common
      * native adapters. MMIO, atomics and unproved translations remain serial.
      * This is a functional candidate, not a frequency or board qualification.
      */
    case object ExperimentalMemoryParallel extends CommonA1MemoryProfile("experimental-memory-parallel") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = false)
    }

    case object ExperimentalRegisteredTranslation extends CommonA1MemoryProfile("experimental-registered-translation") {
        override def validate(config: FpgaNextConfig, boundary: CommonCpuTilePortParams): Unit =
            validateMemory(config, boundary, registered = true)
    }

    private def validateMemory(config: FpgaNextConfig, boundary: CommonCpuTilePortParams, registered: Boolean): Unit = {
        val p = config.coreParams
        require(config.issueWidth == 2 && p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2,
            "A1 memory-parallel keeps the two-wide architectural backend")
        require(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.storeBufferEntries == 2,
            "A1 memory-parallel requires explicit ROB16/PRF48/LSU4/SB2 ownership")
        require(config.lsuEntries == 4 && config.dataTranslationEntries == 16 &&
            config.virtualRamLoadPrecheck && config.canonicalVirtualStoreOverlap &&
            config.independentDemandAdmission && config.translationHitFlow == !registered &&
            config.registeredDataTranslation == registered && p.registeredDataTranslation == registered &&
            config.dataTlbWriteReadReuse &&
            config.loadOrderOlderRetire,
            "A1 memory-parallel must receive its complete final memory configuration")
        require(p.virtualRamLoadPrecheck && p.canonicalVirtualStoreOverlap && p.loadOrderOlderRetire &&
            p.registeredMemoryAddress && p.registeredMemoryRequests && p.registeredTranslationHeads &&
            p.registeredTranslatedResponses && p.registeredLoadReplay && p.registeredFabricBoundary &&
            p.registeredLoadIssueForwarding,
            "A1 memory-parallel must preserve checked permission, replay and actual return boundaries")
        require(config.cache.readMshrs == 2 && config.cache.responseEntries == 2 &&
            config.cache.writebackEntries == 2 && config.cache.independentDemandAdmission &&
            config.internalLineGrant && boundary.homeAcquireEntries == 2 && boundary.homeWritebackEntries == 2,
            "A1 memory-parallel does not enlarge cache/Home transaction credits")
        require(p.dataReturnHandleBits == 0 && !p.taggedStoreReturns && p.postedProofConfig.isEmpty &&
            !p.memoryProofFrontier && !p.pendingVirtualStoreProof && !p.frozenStoreProofEnabled &&
            !p.fastBufferedStoreRetire && !p.fastHeadLoadRetire,
            "A1 memory-parallel supports ordered actual CPU replies, not tagged or posted ownership")
        require(!config.precheckedDataRequestFlow && !config.physicalLoadIngressFlow &&
            !config.translatedResponseEmptyFlow,
            "A1 memory-parallel keeps registered ingress, checked requests and CPU response storage")
    }

    /** Build from the public A1 memory baseline. All other options are retained.
      * Reject an already modified memory policy instead of silently replacing
      * its caller-selected capacities or permission/return behavior.
      * Supply the returned configuration AND the profile to CommonA1CpuTile;
      * the tile validates, but does not reapply or overwrite, this configuration.
      */
    def experimentalMemoryParallel(
        base: FpgaNextConfig = FpgaNextConfig.Selected.copy(internalLineGrant = true)
    ): FpgaNextConfig = {
        require(base.lsuEntries == 2 && base.dataTranslationEntries == 8 &&
            !base.virtualRamLoadPrecheck && !base.canonicalVirtualStoreOverlap &&
            !base.independentDemandAdmission && !base.translationHitFlow && !base.dataTlbWriteReadReuse &&
            !base.loadOrderOlderRetire && !base.registeredDataTranslation,
            "build A1 memory-parallel from the unchanged Selected memory policy, not another memory candidate")
        val result = base.copy(lsuEntries = 4, dataTranslationEntries = 16,
            virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true,
            independentDemandAdmission = true, translationHitFlow = true,
            dataTlbWriteReadReuse = true, loadOrderOlderRetire = true)
        ExperimentalMemoryParallel.validate(result, CommonCpuTilePortParams())
        result
    }
    /** M2 changes only the result/permission boundary, retaining all queue/cache/Home credits. */
    def experimentalRegisteredTranslation(base: FpgaNextConfig): FpgaNextConfig = {
        ExperimentalMemoryParallel.validate(base, CommonCpuTilePortParams())
        val result = base.copy(translationHitFlow = false, registeredDataTranslation = true)
        ExperimentalRegisteredTranslation.validate(result, CommonCpuTilePortParams())
        result
    }

}
