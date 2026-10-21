package soc.platform

import soc.core.inorder.FiveStageConfig
import soc.core.ooo.FpgaNextConfig
import soc.ip.clock.{ClockResource, CmuParams}

/** Explicit CPU choices for ONE platform. Frequencies are initial STA targets,
  * never a claim that this integration has routed at those frequencies.
  * Both choices use the same firmware image and fixed fabric/timebase metadata.
  */
case class CommonCpuProfile(kind: String, clocks: CommonClockConfig, clockProfile: String = "production") {
    require(Set("i1", "a1").contains(kind))
    require(Set("production", "boot50-static", "performance300-static").contains(clockProfile))
    val independentFixedDomains = clockProfile != "production"
    require(clockProfile != "boot50-static" || clocks == CommonClockConfig(50000000, 50000000, 250000000),
        "boot50-static requires CPU50/fabric50/TIME250")
    require(clockProfile != "performance300-static" ||
        (kind == "i1" && clocks == CommonClockConfig(300000000, 250000000, 250000000)),
        "performance300-static requires I1 CPU300/fabric250/TIME250")
    val fabricHz = clocks.fabricClockHz.toInt
    val cpuHz = clocks.clockFrequencyHz.toInt
    val aonHz = 50000000
    val uartHz = 50000000
    val ddrUiHz = 250000000
    val uartBaud = 460800
    val fpga: FpgaNextConfig = FpgaNextConfig.Selected.copy(internalLineGrant = true, experimentalTriSpeedEthernet = true)
    val features = CommonPlatformFeatures(true, true, true, true)
    val boundary = CommonCpuTilePortParams()
    val i1: FiveStageConfig = FiveStageConfig(
        resetVector = CommonPlatformAbi.romBase, trapVector = CommonPlatformAbi.romBase + 0x100,
        cacheableBase = CommonPlatformAbi.ramBase, cacheableBytes = fpga.ddrBytes,
        pipelineProfile = "fpga8", fpgaTimingCuts = true, multiplyMode = "dsp-tiled",
        instructionCacheBytes = 32768, dataCacheBytes = 32768, branchPredictorEntries = 128,
        earlyMemoryIssue = true, overlapWriteLookup = true, withUser = true, withSupervisor = true,
        withSv39 = true, pmpEntries = 8, tlbEntries = 16, bankedTlbProofs = true,
        withC = true, withA = true, withF = true, withD = true,
        coherentCaches = true, coherentCacheWays = 2, coherentControlCuts = true,
        coherentBandwidth = true, fastDataTranslation = true, coherentWholeLine = true,
        cacheFetchPredecode = true, indexedDataProofs = true, overlapDataRetirement = true,
        directFastDataIssue = true, coherentLineGrants = true, coherentMissTurnover = true,
        coherentWritebackOverlap = true, coherentReadOverlap = true, dataReplyHandoff = true,
        withAia = true, externalFenceICompletion = true)
    // Fixed seven-resource CMU ABI. TIME is an independent fixed-domain rate,
    // not a child of CPU; CPU resource 1 is the ROM's runtime frequency source.
    val cmu = CmuParams(aonHz, Seq(
        ClockResource("AON", aonHz), ClockResource("CPU", cpuHz),
        ClockResource("TIME", clocks.timebaseHz),
        ClockResource("UART", uartHz, canGate = true), ClockResource("DDR_UI", ddrUiHz),
        ClockResource("GMAC_TX", 125000000, canGate = true),
        ClockResource("GMAC_RX", 125000000, canGate = true)), timeoutCycles = 65536)
}
object CommonCpuProfile {
    val I1 = CommonCpuProfile("i1", CommonClockConfig(300000000, 250000000, 250000000))
    val A1 = CommonCpuProfile("a1", CommonClockConfig(100000000, 250000000, 250000000))
    val I1Performance300 = CommonCpuProfile("i1", CommonClockConfig(300000000, 250000000, 250000000),
        "performance300-static")
    val I1Boot50 = CommonCpuProfile("i1", CommonClockConfig(50000000, 50000000, 250000000), "boot50-static")
    val A1Boot50 = CommonCpuProfile("a1", CommonClockConfig(50000000, 50000000, 250000000), "boot50-static")
    def named(kind: String, clockProfile: String = "production"): CommonCpuProfile = {
        require(Set("production", "boot50-static", "performance300-static").contains(clockProfile), "unreviewed clock profile")
        if (clockProfile == "performance300-static") {
            require(kind == "i1", "performance300-static is reviewed only for I1")
            return I1Performance300
        }
        if (clockProfile == "boot50-static") return kind match {
            case "i1" => I1Boot50
            case "a1" => A1Boot50
            case _ => throw new IllegalArgumentException("explicit i1 or a1 CPU profile required")
        }
        kind match {
            case "i1" => I1
            case "a1" => A1
            case _ => throw new IllegalArgumentException("explicit i1 or a1 CPU profile required")
        }
    }
}
