package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.ethernet._
import soc.bus.tilelink.TLParams

class SelfGmacParamsSpec extends AnyFunSuite {
    test("native GMAC CSR and frame/MDIO contracts reject invalid parameters") {
        intercept[IllegalArgumentException](GmacParams(base = 1))
        intercept[IllegalArgumentException](GmacParams(ports = Seq.empty))
        intercept[IllegalArgumentException](GmacParams(ports = Seq.fill(5)(Rgmii1G)))
        intercept[IllegalArgumentException](GmacParams(maxFrameBytes = 63))
        intercept[IllegalArgumentException](GmacParams(mdcHz = 2500001))
        intercept[IllegalArgumentException](GmacParams(controlClockHz = 5000000))
        intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new TileLinkGmacControl(
            params = TLParams(dataWidth = 32))))
        intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new MdioClause22(clockHz = 1)))
    }
    test("standalone control and 64-bit CRC export without TEMAC or CPU dependencies") {
        val single = ChiselStage.emitCHIRRTL(new TileLinkGmacControl())
        assert(single.contains("module MdioClause22") && single.contains("module TileLinkGmacControl"))
        assert(!single.contains("axi_ethernet") && !single.contains("IntegerCore"))
        val mixed = ChiselStage.emitCHIRRTL(new TileLinkGmacControl(
            GmacParams(ports = Seq(Rgmii1G, Xgmii10G))))
        assert(mixed.contains("ports") && mixed.contains("[2]"))
        val crc = ChiselStage.emitCHIRRTL(new EthernetCrc32Gsim)
        assert(crc.contains("module EthernetCrc32Gsim"))
    }
    test("store-and-forward GMII and DMA adapter remain independent IPs") {
        for (bytes <- Seq(64, 2048, 16384)) {
            assert(ChiselStage.emitCHIRRTL(new GmiiFrameTx(bytes)).contains("module GmiiFrameTx"))
            assert(ChiselStage.emitCHIRRTL(new GmiiFrameRx(bytes)).contains("module GmiiFrameRx"))
        }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new GmiiFrameTx(63)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new GmiiFrameRx(4097)) }
        val adapter = ChiselStage.emitCHIRRTL(new EthernetDmaFrameAdapter)
        assert(!adapter.contains("EthernetPacketDma") && !adapter.contains("MachineCore"))
        val combined = ChiselStage.emitCHIRRTL(new SelfGmacDmaGsim)
        assert(combined.contains("EthernetPacketDma") && combined.contains("GmiiFrameTx"))
        assert(!combined.contains("MachineCore") && !combined.contains("axi_ethernet_0"))
    }
}
