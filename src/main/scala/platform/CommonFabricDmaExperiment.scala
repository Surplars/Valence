package soc.platform

import soc.core.ooo.FpgaNextConfig

/** Explicit shared-fabric selection, independent of CPU-private configuration.
  * Neither selection is a default, runtime qualification or board signoff.
  */
sealed abstract class CommonFabricDmaExperiment(val name: String, val probeOverlap: Boolean)

object CommonFabricDmaExperiment {
    case object ReadBaseline extends CommonFabricDmaExperiment("read-baseline", false)
    case object ProbeAcquire extends CommonFabricDmaExperiment("probe-acquire", true)

    def named(name: String): CommonFabricDmaExperiment = name match {
        case "read-baseline" => ReadBaseline
        case "probe-acquire" => ProbeAcquire
        case _ => throw new IllegalArgumentException("expected read-baseline|probe-acquire fabric experiment")
    }

    def fromOptions(cpuArgument: String, options: Seq[String]): Option[CommonFabricDmaExperiment] = {
        val prefix = "--experimental-fabric-dma="
        val selected = options.filter(_.startsWith(prefix))
        require(selected.size <= 1, "duplicate fabric DMA experiment")
        require(selected.isEmpty || cpuArgument == "a1", "fabric DMA experiment requires the explicit a1 CLI")
        selected.headOption.map(value => named(value.stripPrefix(prefix)))
    }

    final case class Resolved(fpga: FpgaNextConfig, completionFlow: Boolean = false,
        readOverlap: Boolean = false, probeOverlap: Boolean = false)

    def resolve(profile: CommonCpuProfile, peripherals: CommonPeripheralConfig,
        boundary: CommonCpuTilePortParams, selection: Option[CommonFabricDmaExperiment],
        runtime: Boolean = false): Resolved = {
        if (selection.isEmpty) return Resolved(profile.fpga)
        require(profile == CommonCpuProfile.A1 && !runtime && !boundary.runtimeMaintenance &&
            !boundary.runtimeCancellation && !boundary.runtimeInterruptHold,
            "fabric DMA experiment requires the static production A1 common platform")
        require(peripherals.memoryCopyDma, "fabric DMA experiment requires the memory-copy DMA peripheral")
        require(boundary.homeAcquireEntries == 2 && boundary.homeWritebackEntries == 2 &&
            boundary.coherent.sourceBits == 3 && boundary.coherent.sinkBits == 1,
            "fabric DMA experiment requires the reviewed common Home boundary")
        require(profile.fpga.ddr.maxOutstanding == 4 && profile.fpga.ddr.maxOutstandingWrites == 2,
            "fabric DMA experiment requires four DDR slots and two write slots")
        val effective = profile.fpga.copy(ddrWriteCollectionFlow = true, dmaLineTransfers = true,
            dmaLineEntries = 2, lineReadChannel = true, dmaLineThresholdRewrite = true,
            dmaSingleReadWait = false)
        Resolved(effective, completionFlow = true, readOverlap = true, probeOverlap = selection.get.probeOverlap)
    }
}
