package soc.platform

/** The selected CPU and peripheral composition, independent of export format.
  * Existing constructors/CLI selectors adapt to this value; it does not invent
  * new legal CPU combinations or mix CPU-private policy into the shared fabric.
  */
case class CommonSocConfig(
    profile: CommonCpuProfile,
    cpuSpec: Option[CommonA1CpuSpec] = None,
    peripherals: CommonPeripheralConfig = CommonPeripheralConfig(),
    a1Experimental: Option[CommonA1ExperimentalSelection] = None
) {
    // Keep the seven-resource software ABI. An absent MAC is not a gated or
    // immediately-drained endpoint, and cannot accept CMU stop requests.
    val cmu = if (peripherals.network) profile.cmu else profile.cmu.copy(
        resources = profile.cmu.resources.zipWithIndex.map { case (resource, index) =>
            if (index == 5 || index == 6) resource.copy(present = false, canGate = false) else resource
        })

    def cpuConfig(boundary: CommonCpuTilePortParams, experimentalRuntime: Boolean = false) =
        CommonA1CpuSpec.resolve(profile, a1Experimental, cpuSpec, boundary, experimentalRuntime)
}
