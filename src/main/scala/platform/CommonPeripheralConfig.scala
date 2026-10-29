package soc.platform

/** Supported composition choices for the common platform, separate from CPU
  * geometry and microarchitecture qualification. Other peripherals remain present.
  * Disabling a device leaves its ABI address unused; it never renumbers devices.
  */
case class CommonPeripheralConfig(jtagDownload: Boolean = true, memoryCopyDma: Boolean = true) {
    val features: CommonPlatformFeatures = CommonPlatformFeatures(
        ethernetControl = true, networkDma = true, jtagDownload = jtagDownload, clockManagement = true,
        memoryCopyDma = memoryCopyDma)
    val mmioRegions: Seq[CommonAddressRegion] = CommonPlatformAbi.cpuMmioRegions(features)

    def validateRuntime(runtimeDebugAdmission: Boolean): Unit =
        require(!runtimeDebugAdmission || jtagDownload,
            "runtime debug admission requires the JTAG RAM-download endpoint")
}

object CommonPeripheralConfig {
    def jtagOption(value: String): CommonPeripheralConfig = value match {
        case "on" => CommonPeripheralConfig(jtagDownload = true)
        case "off" => CommonPeripheralConfig(jtagDownload = false)
        case _ => throw new IllegalArgumentException("--jtag-download must be on or off")
    }
}
