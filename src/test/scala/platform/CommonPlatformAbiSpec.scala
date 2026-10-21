package platform

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

/** Pure Scala only: independent literal oracles and configuration checks, no simulator/elaborator. */
class CommonPlatformAbiSpec extends AnyFunSuite {
    private val abi = CommonPlatformAbi
    private val fullFeatures = CommonPlatformFeatures(true, true, true, true)
    private def hex(value: String): BigInt = BigInt(value, 16)
    private def source(relative: String): String = Files.readString(
        Paths.get(sys.props.getOrElse("chisel.project.root", ".")).resolve(relative), StandardCharsets.UTF_8
    )

    test("version 1 keeps the A1 board ROM and explicit RAM capacities") {
        assert(abi.versionMajor == 1 && abi.versionMinor == 0)
        assert(abi.romBase == hex("80000000") && abi.romBytes == 131072 && abi.romWords == 32768)
        assert(abi.ramBase == hex("80200000") && abi.onChipRamBytes == 1048576)
        assert(abi.defaultDdrBytes == hex("20000000"))
        assert(abi.supportedDdrBytes == Seq(hex("20000000"), hex("40000000"), hex("80000000")))
        assert(abi.lineBytes == 64 && abi.beatBytes == 8 && abi.beatsPerLine == 8)
    }

    test("CPU decode is exact, disjoint and excludes both internal IMSIC pages") {
        val expected = Map(
            "timer" -> (hex("02000000"), BigInt(65536)),
            "m-aplic" -> (hex("0c000000"), BigInt(16384)),
            "s-aplic" -> (hex("0c004000"), BigInt(16384)),
            "uart" -> (hex("10000000"), BigInt(8)),
            "dma" -> (hex("10001000"), BigInt(40)),
            "network-dma" -> (hex("10002000"), BigInt(256)),
            "jtag" -> (hex("10003000"), BigInt(64)),
            "ethernet" -> (hex("10040000"), BigInt(262144)),
            "cmu" -> (hex("10080000"), BigInt(4096))
        )
        val regions = abi.cpuMmioRegions(fullFeatures)
        assert(regions.map(r => r.name -> (r.base, r.bytes)).toMap == expected)
        for (a <- regions; b <- regions if a.name != b.name) assert(!a.overlaps(b))
        for (region <- regions) {
            assert(region.contains(region.base) && region.contains(region.endExclusive - 1))
            assert(!region.contains(region.base - 1) && !region.contains(region.endExclusive))
            assert(!region.overlaps(abi.rom))
            assert(abi.internalMsiPages.forall(msi => !region.overlaps(msi)))
        }
        assert(!abi.imsicCpuLoadStoreMapped)
        assert(abi.internalMsiPages.map(_.base) == Seq(hex("24000000"), hex("28000000")))
        assert(abi.internalMsiPages.forall(_.bytes == 4096))
        assert(abi.nativeGmacPortBytes == 4096) // Do not confuse one native port with the route aperture.
    }

    test("optional windows stay opt-in and network DMA retains its stream dependency") {
        assert(abi.cpuMmioRegions(CommonPlatformFeatures()).map(_.name).toSet ==
            Set("timer", "m-aplic", "s-aplic", "uart", "dma"))
        intercept[IllegalArgumentException] { CommonPlatformFeatures(networkDma = true) }
        assert(abi.cpuMmioRegions(CommonPlatformFeatures(ethernetControl = true)).size == 6)
    }

    test("interrupt source numbering and M/S target contract are preserved") {
        assert(abi.interruptSources == 31 && abi.interruptIdentities == 127 && abi.interruptHart == 0)
        assert(Seq(abi.uartInterruptSource, abi.dmaInterruptSource, abi.ethernetInterruptSource,
            abi.networkDmaInterruptSource, abi.clockManagementInterruptSource) == Seq(3, 4, 5, 6, 7))
        assert((1 to 31).map(abi.interruptBit) == (0 until 31))
        intercept[IllegalArgumentException] { abi.interruptBit(0) }
        intercept[IllegalArgumentException] { abi.interruptBit(32) }
        assert(abi.imsicFiles == 2 && abi.imsicMachineFile == 0 && abi.imsicSupervisorFile == 1)
        assert(abi.imsicGuestFiles == 0)
        assert(Seq(abi.machineTimerCause, abi.machineExternalCause, abi.supervisorExternalCause) == Seq(7, 11, 9))
        assert(abi.mtimeAddress == hex("0200bff8") && abi.mtimecmpAddress == hex("02004000"))
    }

    test("monitor reach and TUI reservation match all four firmware memory layouts") {
        val cases = Seq(
            (hex("100000"), false, hex("802fc000")),
            (hex("20000000"), true, hex("a01fc000")),
            (hex("40000000"), true, hex("c01fc000")),
            (hex("80000000"), true, hex("ffff8000"))
        )
        for ((bytes, ddr, monitor) <- cases) {
            val memory = CommonBoardMemory(bytes, ddr)
            assert(memory.monitorBase == monitor && memory.monitor.bytes == 16384)
            assert(memory.imageEndExclusive == monitor && memory.imageLimit == monitor - hex("80200000"))
            assert(memory.ram.contains(memory.monitor.endExclusive - 1))
            assert(!memory.ram.overlaps(abi.rom))
            assert(abi.cpuMmioRegions(fullFeatures).forall(r => !memory.ram.overlaps(r)))
            if (ddr) {
                val menu = CommonBoardMemory(bytes, ddr, bootMenu = true)
                assert(menu.imageEndExclusive == monitor - 524288)
            }
        }
        intercept[IllegalArgumentException] { CommonBoardMemory(4096, externalDdr = false) }
        intercept[IllegalArgumentException] { CommonBoardMemory(hex("100000"), externalDdr = true) }
        intercept[IllegalArgumentException] { CommonBoardMemory(hex("100000"), false, bootMenu = true) }
    }

    test("CPU rate changes never relabel the fabric timer, firmware budget or DT timebase") {
        val clocks = CommonClockConfig(300000000L, 50000000L, 50000000L)
        assert(clocks.firmwareDefines == Map("CPU_CLOCK_HZ" -> 300000000L,
            "FABRIC_CLOCK_HZ" -> 50000000L, "TIMEBASE_HZ" -> 50000000L))
        assert(clocks.deviceTreeProperties == Map("clock-frequency" -> 300000000L,
            "timebase-frequency" -> 50000000L))
        assert(clocks.romClockSummary == "cpu_hz=300000000 fabric_hz=50000000 timebase_hz=50000000")
        assert(clocks.legacyFirmwareCpuHz == 50000000L)
        val slower = clocks.copy(clockFrequencyHz = 40000000L)
        assert(slower.timebaseHz == clocks.timebaseHz && slower.legacyFirmwareCpuHz == clocks.legacyFirmwareCpuHz)
        assert(CommonClockConfig(40000000L, 40000000L, 40000000L).legacyFirmwareCpuHz == 40000000L)
        val independent = CommonClockConfig(50000000L, 100000000L, 250000000L)
        assert(independent.legacyFirmwareCpuHz == 250000000L)
        assert(independent.copy(fabricClockHz = 50000000L).timebaseHz == 250000000L)
        intercept[IllegalArgumentException] { clocks.copy(timebaseHz = 0) }
        intercept[IllegalArgumentException] { clocks.copy(clockFrequencyHz = 0) }
        // Configuration acceptance is not frequency, timing, CDC or board qualification.
    }

    test("transport agreement preserves source, sink, native owner and whole-line capability") {
        val shape = CommonTransportShape(3, 2, 5, internalLineGrant = true)
        shape.requireCompatible(shape.copy())
        assert(shape.lineGrantDataBits == 512)
        for (other <- Seq(shape.copy(sourceBits = 2), shape.copy(sinkBits = 1), shape.copy(ownerBits = 4),
            shape.copy(internalLineGrant = false))) {
            intercept[IllegalArgumentException] { shape.requireCompatible(other) }
        }
        intercept[IllegalArgumentException] { shape.copy(sourceBits = 0) }
        intercept[IllegalArgumentException] { shape.copy(sinkBits = 0) }
        intercept[IllegalArgumentException] { shape.copy(ownerBits = 0) }
    }

    test("maintenance requires every response owner and both transport endpoints, then matching I invalidation") {
        val done = CommonMaintenanceCompletion(
            requestInFlight = true, olderCpuRequestsCompleted = true, frontendQuiescent = true,
            cacheFlushCompleted = true, homeDrainCompleted = true, mmioResponsesCompleted = true,
            transactionSourcesRetired = true, grantSinksAcknowledged = true, lineGrantTransportEmpty = true,
            reservationClearCompleted = true, cpuTransportEmpty = true, fabricTransportEmpty = true
        )
        assert(done.memoryAcknowledgementAllowed)
        assert(!done.fetchResumeAllowed(instructionInvalidationObserved = false))
        assert(done.fetchResumeAllowed(instructionInvalidationObserved = true))
        val incomplete = Seq(
            done.copy(requestInFlight = false), done.copy(olderCpuRequestsCompleted = false),
            done.copy(frontendQuiescent = false), done.copy(cacheFlushCompleted = false),
            done.copy(homeDrainCompleted = false), done.copy(mmioResponsesCompleted = false),
            done.copy(transactionSourcesRetired = false), done.copy(grantSinksAcknowledged = false),
            done.copy(lineGrantTransportEmpty = false), done.copy(reservationClearCompleted = false),
            done.copy(cpuTransportEmpty = false), done.copy(fabricTransportEmpty = false)
        )
        for (state <- incomplete) {
            assert(!state.memoryAcknowledgementAllowed)
            assert(!state.fetchResumeAllowed(instructionInvalidationObserved = true))
        }
    }

    test("shared definitions agree with current board and AIA defaults without changing historical profiles") {
        val board = soc.core.ooo.BoardSocConfig
        val aplic = soc.ip.interrupt.AplicParams()
        val imsic = soc.ip.interrupt.ImsicParams()
        assert(board.romBase == abi.romBase && board.romBytes == abi.romBytes && board.romWords == abi.romWords)
        assert(board.ramBase == abi.ramBase && board.ramBytes == abi.onChipRamBytes)
        assert(board.ddrBytes == abi.defaultDdrBytes && board.issueWidth == 2 && board.clockHz == 40000000)
        assert(aplic.base == abi.aplicMachineBase && aplic.sources == abi.interruptSources)
        assert(aplic.identities == abi.interruptIdentities && aplic.msiBase == abi.imsicMachineBase)
        assert(imsic.machineBase == abi.imsicMachineBase && imsic.supervisorBase == abi.imsicSupervisorBase)
        assert(imsic.files == abi.imsicFiles && imsic.guestFiles == abi.imsicGuestFiles)
        // Compatibility guard only; the old I1 image is explicitly not common-platform qualification.
        val oldI1 = soc.core.inorder.FiveStageSocConfig()
        assert(oldI1.bootRomBase == hex("10000") && oldI1.bootRomBytes == 4096)
        assert(oldI1.networkDmaBase == hex("10005000"))
    }

    test("firmware retains the full ROM, TUI, CRC and bounded netboot contracts") {
        val linker = source("fpga/firmware/bootrom.ld")
        assert(linker.contains("ROM (rx) : ORIGIN = 0x80000000, LENGTH = 128K"))
        assert(source("fpga/firmware/build.py").contains("ROM_BYTES = 128 * 1024"))
        val memory = source("fpga/firmware/board_memory.h")
        assert(memory.contains("#define RAM_BASE 0x80200000UL"))
        assert(memory.contains("#define DIAG_RESERVE_BYTES 0x80000UL"))
        assert(abi.uartDownloadChunkBytes == 256 && abi.crcTableBytes.toSet == Set(64, 1024, 2048, 4096))
        assert(abi.ramVerifySweepBytes == 65536 && abi.ramVerifySweepPasses == 2 && abi.netbootRxStopAbi == 2)
        val net = source("fpga/firmware/ethernet_dma.h")
        assert(net.contains("#define VALENCE_NET_DMA_BASE 0x10002000UL"))
        assert(net.contains("#define VALENCE_NET_DMA_IRQ 6"))
        assert(net.contains("#define VALENCE_NET_DMA_RX_STOP 0x90"))
        assert(net.contains("#define VALENCE_NET_DMA_CAPABILITIES 0x98"))
        assert(abi.networkDmaRxStopOffset == 0x90 && abi.networkDmaCapabilitiesOffset == 0x98)
        assert(abi.networkDmaRxStopCapability == 1 && abi.nativeGmacRxStopCapability == 256)
        assert(source("fpga/firmware/valence_gmac.h").contains("#define VGMAC_RX_STOP 0x90"))
        assert(abi.nativeGmacRxStopOffset == 0x90)
    }
}
