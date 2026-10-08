package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.dma.{EthernetPacketDma, NetworkDmaConfig}
import soc.ip.ethernet.GmiiFrameRx
import soc.core.ooo.{BoardSocTop, CacheTagConfig, CoherentCacheConcurrency, DdrBridgeConfig}

class NetworkDmaConfigSpec extends AnyFunSuite {
    test("independent capacities reject malformed and duplicate export options") {
        for (bad <- Seq(0, 3, 17, 32)) {
            intercept[IllegalArgumentException](NetworkDmaConfig(macRxSlots = bad))
            intercept[IllegalArgumentException](NetworkDmaConfig(postedRxSlots = bad))
            intercept[IllegalArgumentException](NetworkDmaConfig(memoryCredits = bad))
        }
        for (bad <- Seq(32, 65, 32768)) {
            intercept[IllegalArgumentException](NetworkDmaConfig(maxFrameBytes = bad))
        }
        val (positional, config) = NetworkDmaConfig.parseArgs(Array("out", "rv64gc", "board",
            "--network-mac-slots=1", "--network-rx-slots=16", "--network-memory-credits=2"))
        assert(positional.toSeq == Seq("out", "rv64gc", "board"))
        assert(config == NetworkDmaConfig(macRxSlots = 1, postedRxSlots = 16, memoryCredits = 2))
        for (bad <- Seq(Array("--network-rx-slots=2", "--network-rx-slots=4"),
            Array("--network-unknown=1"), Array("--network-mac-slots"))) {
            intercept[IllegalArgumentException](NetworkDmaConfig.parseArgs(bad))
        }
        assert(NetworkDmaConfig.parseArgs(Array("out"))._2 == NetworkDmaConfig.Default)
    }
    test("elaboration stores selected owners and bounded descriptors, never maximum arrays") {
        for ((slots, credits) <- Seq((1, 1), (4, 4), (16, 2))) {
            val rtl = ChiselStage.emitCHIRRTL(new EthernetPacketDma(ramBytes = BigInt(1) << 31,
                postedRxSlots = slots, memoryCredits = credits))
            assert(rtl.contains(s"reg queuedAddressWords : UInt<30>[$slots]"))
            assert(rtl.contains(s"reg queuedCapacity : UInt<12>[$slots]"))
            assert(rtl.contains(s"reg completedMetadata : UInt<17>[$slots]"))
            assert(!rtl.contains("reg queuedAddress : UInt<64>"))
        }
        for (slots <- Seq(1, 4, 16)) {
            val rtl = ChiselStage.emitCHIRRTL(new GmiiFrameRx(frameSlots = slots))
            assert(rtl.contains(s"smem buffer : UInt<32>[${slots * 512}]"))
            assert(rtl.contains(s"reg lengths : UInt<12>[$slots]"))
        }
    }
    test("actual managed board passes independent capacities into native MAC and DMA") {
        val rtl = ChiselStage.emitCHIRRTL(new BoardSocTop(
            socClockHz = 100000000, externalDdr = true, timingProfile = "staged-fetch-turnover",
            uartBaud = 460800, isaProfile = "rv64gc", issueWidth = 2,
            peripheralClockHz = 50000000, clockManagementHz = 50000000, ddrUiClockHz = 250000000,
            ethernetControl = true, ethernetDma = true, managedPeripherals = true,
            ddrMemoryBytes = BigInt(2147483648L), instructionLineCacheLines = 512, dataCacheLines = 512,
            cacheConcurrency = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2),
            ddrBridge = DdrBridgeConfig(maxOutstanding = 4, maxBurstBeats = 16),
            loadIssueForwarding = Some(true), tagConfig = CacheTagConfig.Aperture, identityDataFlow = true,
            networkDmaConfig = NetworkDmaConfig(macRxSlots = 1, postedRxSlots = 16, memoryCredits = 2, postedTxSlots = 4)))
        val ownerGeometry = rtl.contains("reg queuedAddressWords : UInt<30>[16]")
        val bankGeometry = rtl.contains("smem buffer : UInt<32>[512]") &&
            rtl.contains("reg lengths : UInt<12>[1]")
        assert(ownerGeometry, "native board must forward sixteen compact descriptor slots")
        assert(bankGeometry, "native board must forward one physical frame bank")
        assert(rtl.contains("module NonBlockingCoherentLineCache"))
        assert(rtl.contains("module NonBlockingCoherentLineHome"))
        assert(rtl.contains("reg tags : UInt<19>[512]"))
        assert(rtl.contains("reg tags : UInt<27>[512]"))
        assert(rtl.contains("regreset responseOwned : UInt<1>[2]"))
        assert(rtl.contains("module TileLinkAxi4OutstandingBridge"))
        assert(rtl.contains("module EthernetTxDescriptorQueue"))
    }

    test("posted TX is absent by default and stores only explicitly selected owners") {
        assert(NetworkDmaConfig.Default.postedTxSlots == 0)
        for (bad <- Seq(-1, 3, 17)) intercept[IllegalArgumentException](NetworkDmaConfig(postedTxSlots = bad))
        assert(NetworkDmaConfig.parseArgs(Array("out", "--network-tx-slots=4"))._2.postedTxSlots == 4)
        val legacy = ChiselStage.emitCHIRRTL(new EthernetPacketDma(ramBytes = 8192))
        val absent = !legacy.contains("module EthernetTxDescriptorQueue")
        assert(absent, "TX-disabled configuration must not instantiate unused owner storage")
        for (slots <- Seq(1, 4, 16)) {
            val rtl = ChiselStage.emitCHIRRTL(new EthernetPacketDma(ramBytes = BigInt(2147483648L), postedTxSlots = slots))
            val selected = rtl.contains(s"reg addressWords : UInt<30>[$slots]") &&
                rtl.contains(s"reg results : UInt<17>[$slots]")
            assert(selected, "TX storage must follow selected bounded owner count")
        }
    }

}
