package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.dma.{EthernetPacketDma, NetworkDmaConfig}
import soc.core.ooo.{BoardSocConfig, BoardSocTop, EthernetSocTop}

class EthernetPacketDmaSpec extends AnyFunSuite {
    test("frame DMA rejects bad regions/capacities and has independent TX/RX staging RAMs") {
        intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new EthernetPacketDma(base = 1)))
        intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new EthernetPacketDma(maxFrameBytes = 63)))
        intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new EthernetPacketDma(ramBytes = 512)))
        val rtl = ChiselStage.emitCHIRRTL(new EthernetPacketDma(ramBytes = 8192))
        assert(rtl.contains("smem txBuffer") && rtl.contains("smem rxBuffer"))
        assert(rtl.contains("module RegisterArbiter"))
        assert(rtl.contains("queueEnabled") && rtl.contains("slotOwned"))
        assert(rtl.contains("completedMetadata") && rtl.contains("queueStopped"))
    }
    test("network DMA is opt-in and actual MAC integration crosses all four streams") {
        intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new BoardSocTop(
            vivadoMemories = false, ethernetDma = true)))
        val legacy = ChiselStage.emitCHIRRTL(new EthernetSocTop())
        assert(!legacy.contains("module EthernetPacketDma"))
        val rtl = ChiselStage.emitCHIRRTL(new EthernetSocTop(timingProfile = "staged-fetch-feedback",
            packetDma = true, networkDmaConfig = NetworkDmaConfig(macRxSlots = 1, postedRxSlots = 16, memoryCredits = 2)))
        assert(rtl.contains("module EthernetPacketDma"))
        val addressWordBits = (BoardSocConfig.ramBase + BoardSocConfig.ddrBytes - 1).bitLength - 3
        assert(rtl.contains(s"reg queuedAddressWords : UInt<$addressWordBits>[16]"))
        val crossings = rtl.linesIterator.count(line => line.trim.startsWith("inst ") &&
            line.contains(" of StreamClockDomainFifo"))
        assert(crossings == 4, s"four distinct stream CDC instances required: $crossings")
        assert(rtl.contains("cpuRelease"))
    }
}
