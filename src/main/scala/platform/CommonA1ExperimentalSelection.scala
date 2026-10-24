package soc.platform

import soc.core.ooo.FpgaNextConfig

/** Explicit CPU-private experiments for the real common platform. This selector
  * is independent of CPU family, clock selection and all shared fabric policy.
  * Neither choice is a timing, dynamic-clock or board qualification.
  */
sealed abstract class CommonA1ExperimentalSelection(val name: String, val rebuild: CommonA1RebuildProfile)

object CommonA1ExperimentalSelection {
    case object FullR1 extends CommonA1ExperimentalSelection("full-r1", CommonA1RebuildProfile.FullR1)
    case object FullR1M3 extends CommonA1ExperimentalSelection("full-r1-m3", CommonA1RebuildProfile.FullR1M3)

    val all: Seq[CommonA1ExperimentalSelection] = Seq(FullR1, FullR1M3)
    def named(name: String): CommonA1ExperimentalSelection = {
        require(all.exists(_.name == name), s"unknown experimental A1 microarchitecture: $name")
        all.find(_.name == name).get
    }

    def config(profile: CommonCpuProfile, selected: Option[CommonA1ExperimentalSelection]): FpgaNextConfig = {
        require(selected.isEmpty || profile.kind == "a1", "experimental A1 microarchitecture requires CPU family a1")
        selected.map(_.rebuild.config).getOrElse(profile.fpga)
    }

    def memoryProfile(selected: Option[CommonA1ExperimentalSelection]): Option[CommonA1MemoryProfile] =
        selected.flatMap(_.rebuild.memoryProfile)

    /** Validate the final tile inputs, never patch shared settings to fit them. */
    def validate(profile: CommonCpuProfile, selected: Option[CommonA1ExperimentalSelection],
        boundary: CommonCpuTilePortParams, experimentalRuntime: Boolean): Unit = selected.foreach { selection =>
        require(profile.kind == "a1", "experimental A1 microarchitecture requires CPU family a1")
        require(Set("production", "boot50-static").contains(profile.clockProfile),
            "experimental A1 microarchitecture does not enable a new clock profile")
        require(profile == CommonCpuProfile.A1 || profile == CommonCpuProfile.A1Boot50,
            "experimental A1 retains the reviewed nominal clock tuple; no implicit 300 MHz selection")
        require(!experimentalRuntime || profile == CommonCpuProfile.A1Boot50,
            "experimental A1 runtime retains the complete boot50 admission contract")
        require(boundary.runtimeMaintenance == experimentalRuntime &&
            boundary.runtimeCancellation == experimentalRuntime && boundary.runtimeInterruptHold == experimentalRuntime,
            "experimental A1 runtime identity must match all three boundary capabilities")
        val actual = config(profile, selected)
        val shared = profile.fpga
        val p = actual.coreParams
        require(actual.isaProfile == "rv64gc" && actual.issueWidth == 2 &&
            p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2 &&
            p.robEntries == 16 && p.physicalRegs == 48 && p.machineSystem &&
            p.compressedInstructions && p.atomicMemory && p.pmpEntries == 16 && p.virtualMemoryLevels == 3 &&
            p.floatingPoint == shared.coreParams.floatingPoint && p.advertiseFloatingPoint,
            "experimental A1 must retain the complete public ISA and architectural geometry")
        require(actual.ramBase == shared.ramBase && actual.ddrBytes == shared.ddrBytes &&
            actual.cacheLineBytes == shared.cacheLineBytes && actual.instructionCacheLines == 512 &&
            actual.dataCacheLines == 512 && actual.cacheWays == 2 && actual.internalLineGrant &&
            actual.ddr == shared.ddr && actual.tags == shared.tags && actual.network == shared.network &&
            actual.experimentalTriSpeedEthernet == shared.experimentalTriSpeedEthernet &&
            actual.triSpeedTxFrameSlots == shared.triSpeedTxFrameSlots,
            "experimental A1 must not change the common aperture, transport, DDR or peripheral policy")
        require(actual.cache.readMshrs == 2 && actual.cache.responseEntries == 2 &&
            actual.cache.writebackEntries == 2 && boundary == CommonCpuTilePortParams(
                runtimeMaintenance = boundary.runtimeMaintenance,
                runtimeCancellation = boundary.runtimeCancellation,
                runtimeInterruptHold = boundary.runtimeInterruptHold),
            "experimental A1 retains common transport geometry and cache/Home credits")
        selection.rebuild.memoryProfile.get.validate(actual, boundary)
    }
}
