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
    val fetchSlots: Int = 1
) {
    final def config: FpgaNextConfig = {
        val baseline = CommonCpuProfile.A1.fpga
        val memory = if (parallelMemory) CommonA1MemoryProfile.experimentalMemoryParallel(baseline) else baseline
        val backend = memory.copy(completionTopology = if (dualCompletion) "dual-owner" else "legacy",
            branchResolutionTopology = if (independentBranch) "execution-mailbox" else "writeback-coupled")
        if (fetchSlots == 2) backend.copy(fetchTransactionSlots = 2, alignedFetchSinglePage = true) else backend
    }

    final def memoryProfile: Option[CommonA1MemoryProfile] =
        if (parallelMemory) Some(CommonA1MemoryProfile.ExperimentalMemoryParallel) else None

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

    lazy val all: Seq[CommonA1RebuildProfile] = Seq(Baseline, Backend, Memory, Combined, BackendBranch, CombinedBranch,
        Frontend, CombinedFrontend, FullCandidate)

    def named(name: String): CommonA1RebuildProfile = {
        require(all.exists(_.name == name), s"unknown explicit A1 rebuild profile: $name")
        all.find(_.name == name).get
    }
}
