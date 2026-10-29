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
    def cpuConfig(boundary: CommonCpuTilePortParams, experimentalRuntime: Boolean = false) =
        CommonA1CpuSpec.resolve(profile, a1Experimental, cpuSpec, boundary, experimentalRuntime)
}
