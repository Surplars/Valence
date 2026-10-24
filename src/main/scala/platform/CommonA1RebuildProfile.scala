package soc.platform

import soc.core.ooo.FpgaNextConfig

/** Explicit A/B configurations for the first A1 rebuild batch. These select
  * CPU-private structure, not a clock source, speed grade or timing sign-off.
  * Public CommonCpuProfile presets and the existing bootable SoC stay unchanged.
  */
sealed abstract class CommonA1RebuildProfile(
    val name: String,
    val dualCompletion: Boolean,
    val parallelMemory: Boolean,
    val independentBranch: Boolean = false,
    val fetchSlots: Int = 1,
    val registeredTranslation: Boolean = false,
    val circularPayload: Boolean = false,
    val completedStoreForward: Boolean = false
) {
    final def config: FpgaNextConfig = {
        val baseline = CommonCpuProfile.A1.fpga
        val memory = if (parallelMemory) CommonA1MemoryProfile.experimentalMemoryParallel(baseline) else baseline
        require(!registeredTranslation || parallelMemory, "M2 requires the explicit four-owner memory policy")
        val translation = if (registeredTranslation)
            CommonA1MemoryProfile.experimentalRegisteredTranslation(memory) else memory
        val backend = translation.copy(circularFetchPayload = circularPayload,
            completedCanonicalStoreForwarding = completedStoreForward,
            completionTopology = if (dualCompletion) "dual-owner" else "legacy",
            branchResolutionTopology = if (independentBranch) "execution-mailbox" else "writeback-coupled")
        if (fetchSlots == 2) backend.copy(fetchTransactionSlots = 2, alignedFetchSinglePage = true) else backend
    }

    final def memoryProfile: Option[CommonA1MemoryProfile] =
        if (registeredTranslation) Some(CommonA1MemoryProfile.ExperimentalRegisteredTranslation)
        else if (parallelMemory) Some(CommonA1MemoryProfile.ExperimentalMemoryParallel) else None

    final def buildTile(boundary: CommonCpuTilePortParams = CommonCpuTilePortParams()): CommonA1CpuTile =
        new CommonA1CpuTile(config, boundary, memoryProfile)
}

object CommonA1RebuildProfile {
    case object Baseline extends CommonA1RebuildProfile("baseline", false, false)
    case object Backend extends CommonA1RebuildProfile("backend", true, false)
    case object Memory extends CommonA1RebuildProfile("memory", false, true)
    case object Combined extends CommonA1RebuildProfile("combined", true, true)

    case object BackendBranch extends CommonA1RebuildProfile("backend-branch", true, false, true)
    case object CombinedBranch extends CommonA1RebuildProfile("combined-branch", true, true, true)

    case object Frontend extends CommonA1RebuildProfile("frontend", false, false, false, 2)
    case object CombinedFrontend extends CommonA1RebuildProfile("combined-frontend", true, true, false, 2)
    case object FullCandidate extends CommonA1RebuildProfile("full-candidate", true, true, true, 2)
    case object FullM2 extends CommonA1RebuildProfile("full-m2", true, true, true, 2, true)
    case object FullR1 extends CommonA1RebuildProfile("full-r1", true, true, true, 2, false, true)
    case object FullM2R1 extends CommonA1RebuildProfile("full-m2-r1", true, true, true, 2, true, true)

    case object FullR1M3 extends CommonA1RebuildProfile("full-r1-m3", true, true, true, 2, false, true, true)

    lazy val all: Seq[CommonA1RebuildProfile] = Seq(Baseline, Backend, Memory, Combined, BackendBranch, CombinedBranch,
        Frontend, CombinedFrontend, FullCandidate, FullM2, FullR1, FullM2R1, FullR1M3)

    def named(name: String): CommonA1RebuildProfile = {
        require(all.exists(_.name == name), s"unknown explicit A1 rebuild profile: $name")
        all.find(_.name == name).get
    }
}
