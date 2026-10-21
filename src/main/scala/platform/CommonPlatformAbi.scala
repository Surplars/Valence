package soc.platform

/** Versioned software/platform contract derived from the current A1 board and firmware.
  * This file is pure configuration: it neither instantiates a CPU nor changes any existing profile.
  * Version 1 preserves the board ROM/MMIO/AIA ABI, not the independent I1 bring-up ABI.
  */
object CommonPlatformAbi {
    val versionMajor = 1
    val versionMinor = 0
    val addressBits = 64
    val dataBits = 64
    val beatBytes = dataBits / 8
    val lineBytes = 64
    val beatsPerLine = lineBytes / beatBytes

    val romBase: BigInt = BigInt("80000000", 16)
    val romBytes: Int = 128 * 1024
    val romWords: Int = romBytes / 4
    val ramBase: BigInt = BigInt("80200000", 16)
    val onChipRamBytes: BigInt = BigInt(1024) * 1024
    val defaultDdrBytes: BigInt = BigInt(512) * 1024 * 1024
    val supportedDdrBytes: Seq[BigInt] = Seq(defaultDdrBytes, BigInt(1) << 30, BigInt(1) << 31)
    val monitorBytes: Int = 0x4000
    val monitorMaxBase: BigInt = BigInt("ffff8000", 16)
    val diagnosticBytes: Int = 0x80000

    val timerBase: BigInt = BigInt("02000000", 16)
    val timerBytes: Int = 65536
    val mtimecmpAddress: BigInt = timerBase + 0x4000
    val mtimeAddress: BigInt = timerBase + 0xbff8
    val aplicMachineBase: BigInt = BigInt("0c000000", 16)
    val aplicDomainBytes: Int = 16384
    val aplicSupervisorBase: BigInt = aplicMachineBase + aplicDomainBytes
    val uartBase: BigInt = BigInt("10000000", 16)
    val uartBytes: Int = 8
    val dmaBase: BigInt = BigInt("10001000", 16)
    val dmaBytes: Int = 40
    val networkDmaBase: BigInt = BigInt("10002000", 16)
    val networkDmaBytes: Int = 256
    val jtagBase: BigInt = BigInt("10003000", 16)
    val jtagBytes: Int = 64
    val ethernetBase: BigInt = BigInt("10040000", 16)
    val ethernetBytes: Int = 0x40000
    val nativeGmacPortBytes: Int = 4096
    val clockManagementBase: BigInt = BigInt("10080000", 16)
    val clockManagementBytes: Int = 4096

    // These pages belong to the internal APLIC -> IMSIC RegisterPort, not CPU load/store decode.
    val imsicMachineBase: BigInt = BigInt("24000000", 16)
    val imsicSupervisorBase: BigInt = BigInt("28000000", 16)
    val imsicPageBytes: Int = 4096
    val imsicCpuLoadStoreMapped: Boolean = false
    val interruptSources: Int = 31
    val interruptIdentities: Int = 127
    val interruptHart: Int = 0
    val imsicFiles: Int = 2
    val imsicMachineFile: Int = 0
    val imsicSupervisorFile: Int = 1
    val imsicGuestFiles: Int = 0
    val machineTimerCause: Int = 7
    val machineExternalCause: Int = 11
    val supervisorExternalCause: Int = 9
    val uartInterruptSource: Int = 3
    val dmaInterruptSource: Int = 4
    val ethernetInterruptSource: Int = 5
    val networkDmaInterruptSource: Int = 6
    val clockManagementInterruptSource: Int = 7

    /** Source numbers are one-based; sources(0) carries source 1. Timer bypasses APLIC. */
    def interruptBit(source: Int): Int = {
        require(source >= 1 && source <= interruptSources)
        source - 1
    }

    val rom = CommonAddressRegion("rom", romBase, romBytes)
    val internalMsiPages: Seq[CommonAddressRegion] = Seq(
        CommonAddressRegion("m-imsic-internal", imsicMachineBase, imsicPageBytes),
        CommonAddressRegion("s-imsic-internal", imsicSupervisorBase, imsicPageBytes)
    )

    /** A decoder aperture does not make every offset/access width legal. Disabled windows are absent. */
    def cpuMmioRegions(features: CommonPlatformFeatures): Seq[CommonAddressRegion] = Seq(
        CommonAddressRegion("timer", timerBase, timerBytes),
        CommonAddressRegion("m-aplic", aplicMachineBase, aplicDomainBytes),
        CommonAddressRegion("s-aplic", aplicSupervisorBase, aplicDomainBytes),
        CommonAddressRegion("uart", uartBase, uartBytes),
        CommonAddressRegion("dma", dmaBase, dmaBytes)
    ) ++ (if (features.networkDma) Seq(CommonAddressRegion("network-dma", networkDmaBase, networkDmaBytes))
          else Seq.empty) ++
        (if (features.jtagDownload) Seq(CommonAddressRegion("jtag", jtagBase, jtagBytes)) else Seq.empty) ++
        (if (features.ethernetControl) Seq(CommonAddressRegion("ethernet", ethernetBase, ethernetBytes))
         else Seq.empty) ++
        (if (features.clockManagement)
             Seq(CommonAddressRegion("cmu", clockManagementBase, clockManagementBytes)) else Seq.empty)

    // Firmware capabilities are opt-in; declaring their ABI does not enable hardware or replace a ROM image.
    val uartDownloadChunkBytes: Int = 256
    val crcTableBytes: Seq[Int] = Seq(64, 1024, 2048, 4096)
    val ramVerifySweepBytes: Int = 65536
    val ramVerifySweepPasses: Int = 2
    val netbootRxStopAbi: Int = 2
    val networkDmaRxStopOffset: Int = 0x90
    val networkDmaCapabilitiesOffset: Int = 0x98
    val networkDmaRxStopCapability: BigInt = 1
    val nativeGmacRxStopOffset: Int = 0x90
    val nativeGmacRxStopCapability: BigInt = BigInt(1) << 8
}

case class CommonAddressRegion(name: String, base: BigInt, bytes: BigInt) {
    require(name.nonEmpty && base >= 0 && bytes > 0 && base + bytes <= (BigInt(1) << 64))
    val endExclusive: BigInt = base + bytes
    def contains(address: BigInt): Boolean = address >= base && address < endExclusive
    def overlaps(other: CommonAddressRegion): Boolean = base < other.endExclusive && other.base < endExclusive
}

case class CommonPlatformFeatures(
    ethernetControl: Boolean = false,
    networkDma: Boolean = false,
    jtagDownload: Boolean = false,
    clockManagement: Boolean = false
) {
    require(!networkDma || ethernetControl, "network DMA requires the Ethernet control/stream endpoint")
}

/** Explicit board-capacity choice; never infer DDR or TUI capability from an image's size. */
case class CommonBoardMemory(ramBytes: BigInt, externalDdr: Boolean, bootMenu: Boolean = false) {
    import CommonPlatformAbi._
    require(if (externalDdr) supportedDdrBytes.contains(ramBytes) else ramBytes == onChipRamBytes)
    require(!bootMenu || externalDdr, "the current TUI/diagnostics firmware requires DDR")
    val ram: CommonAddressRegion = CommonAddressRegion("ram", ramBase, ramBytes)
    val monitorBase: BigInt = (ram.endExclusive - monitorBytes).min(monitorMaxBase)
    val monitor: CommonAddressRegion = CommonAddressRegion("monitor", monitorBase, monitorBytes)
    val imageEndExclusive: BigInt = monitorBase - (if (bootMenu) diagnosticBytes else 0)
    val imageLimit: BigInt = imageEndExclusive - ramBase
    require(imageLimit >= 2 * ramVerifySweepBytes)
    require(!bootMenu || imageEndExclusive >= BigInt("80310000", 16))
}

/** Nominal configuration, not measured Fmax or a supported clock-gating/reset policy.
  * mtime advances once per timebase cycle, independently of CPU/fabric rates.
  * A1's current synchronous board is represented by all three frequencies being equal.
  * Consumers must generate firmware, ROM reporting and DT from the same instance.
  */
case class CommonClockConfig(clockFrequencyHz: Long, fabricClockHz: Long, timebaseHz: Long) {
    require(clockFrequencyHz > 0 && fabricClockHz > 0 && timebaseHz > 0)
    def firmwareDefines: Map[String, Long] = Map(
        "CPU_CLOCK_HZ" -> clockFrequencyHz,
        "FABRIC_CLOCK_HZ" -> fabricClockHz,
        "TIMEBASE_HZ" -> timebaseHz
    )
    def deviceTreeProperties: Map[String, Long] = Map(
        "clock-frequency" -> clockFrequencyHz,
        "timebase-frequency" -> timebaseHz
    )
    def romClockSummary: String =
        s"cpu_hz=$clockFrequencyHz fabric_hz=$fabricClockHz timebase_hz=$timebaseHz"
    // Existing firmware's misleading CPU_HZ name drives rdtime budgets. Never put the new CPU rate here.
    def legacyFirmwareCpuHz: Long = timebaseHz
}

/** Endpoint identity widths are negotiated explicitly, not collapsed to a single in-flight token.
  * ownerBits is the native request/return-owner payload width, independent of TileLink source/sink.
  * An adapter with remapping needs its own lossless lifetime proof; this direct transport forbids it.
  */
case class CommonTransportShape(sourceBits: Int, sinkBits: Int, ownerBits: Int, internalLineGrant: Boolean) {
    require(sourceBits >= 1 && sinkBits >= 1 && ownerBits >= 1)
    val lineGrantDataBits: Int = CommonPlatformAbi.lineBytes * 8
    def requireCompatible(peer: CommonTransportShape): Unit =
        require(this == peer, "transport must preserve source, sink, native owner and lineGrant capability")
}

/** Pure acceptance checklist for a maintenance epoch, not a hardware acknowledgement generator.
  * All observations must refer to the SAME request/epoch and be safely observed in its completion domain.
  * Empty transport alone is insufficient. Sources retire only after responses reach their owner;
  * Grant sinks remain owned until E GrantAck reaches Home, including the optional whole-line path.
  * B/C/D/E, lineGrant and outstanding native responses keep progressing while new work is stopped.
  */
case class CommonMaintenanceCompletion(
    requestInFlight: Boolean,
    olderCpuRequestsCompleted: Boolean,
    frontendQuiescent: Boolean,
    cacheFlushCompleted: Boolean,
    homeDrainCompleted: Boolean,
    mmioResponsesCompleted: Boolean,
    transactionSourcesRetired: Boolean,
    grantSinksAcknowledged: Boolean,
    lineGrantTransportEmpty: Boolean,
    reservationClearCompleted: Boolean,
    cpuTransportEmpty: Boolean,
    fabricTransportEmpty: Boolean
) {
    def memoryAcknowledgementAllowed: Boolean = requestInFlight && olderCpuRequestsCompleted &&
        frontendQuiescent && cacheFlushCompleted && homeDrainCompleted && mmioResponsesCompleted &&
        transactionSourcesRetired && grantSinksAcknowledged && lineGrantTransportEmpty &&
        reservationClearCompleted && cpuTransportEmpty && fabricTransportEmpty

    // Invalidation follows memory acknowledgement; fetch resumes only after the matching invalidation.
    def fetchResumeAllowed(instructionInvalidationObserved: Boolean): Boolean =
        memoryAcknowledgementAllowed && instructionInvalidationObserved
}
