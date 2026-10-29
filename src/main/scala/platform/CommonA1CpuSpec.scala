package soc.platform

import soc.core.ooo.{BackendCapacityConfig, FpgaNextConfig}

/** CPU-private capacities for the generic static, two-wide A1 platform.
  * Owners are concurrent memory reservations, not issue/return ports.
  * Legal capacity selections are not a claim of CPU behavioral qualification.
  */
case class CommonA1CpuSpec(lsuOwners: Int, robEntries: Int = 16, physicalRegs: Int = 48) {
    require(Set(2, 4).contains(lsuOwners), "common A1 LSU owners must be 2 or 4")
    // Keep baseline overrides absent: None versus Some(default) is part of the
    // existing effective-config identity. The shared type owns legality checks.
    val backendCapacity: BackendCapacityConfig = BackendCapacityConfig(
        Option.when(robEntries != 16)(robEntries), Option.when(physicalRegs != 48)(physicalRegs))
    val name: String = if (robEntries == 16 && physicalRegs == 48) s"generic-lsu-owners-$lsuOwners"
        else s"generic-rob-$robEntries-prf-$physicalRegs-lsu-owners-$lsuOwners"
}

object CommonA1CpuSpec {
    def lsuOption(value: String): CommonA1CpuSpec = value match {
        case "2" => CommonA1CpuSpec(2)
        case "4" => CommonA1CpuSpec(4)
        case _ => throw new IllegalArgumentException("--a1-lsu-owners must be 2 or 4")
    }

    /** One resolver for hardware, export identity and effective CPU metadata.
      * Absence preserves the existing public/experimental resolution exactly.
      */
    def resolve(profile: CommonCpuProfile, selected: Option[CommonA1ExperimentalSelection],
        spec: Option[CommonA1CpuSpec], boundary: CommonCpuTilePortParams,
        experimentalRuntime: Boolean = false): FpgaNextConfig = {
        spec.foreach { _ =>
            require(profile == CommonCpuProfile.A1,
                "explicit CPU specification requires the generic A1 production static clock profile")
            require(selected.isEmpty && !experimentalRuntime && !boundary.runtimeMaintenance &&
                !boundary.runtimeCancellation && !boundary.runtimeInterruptHold,
                "explicit CPU specification cannot be combined with an experimental or runtime profile")
        }
        CommonA1ExperimentalSelection.validate(profile, selected, boundary, experimentalRuntime)
        val original = CommonA1ExperimentalSelection.config(profile, selected)
        spec.map(s => original.copy(lsuEntries = s.lsuOwners,
            robEntries = s.backendCapacity.robEntries.orElse(original.robEntries),
            physicalRegs = s.backendCapacity.physicalRegs.orElse(original.physicalRegs))).getOrElse(original)
    }
}
