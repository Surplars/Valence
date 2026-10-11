package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo._

class DdrWriteCollectionConfigSpec extends AnyFunSuite {
    test("write collection flow is independent and does not change the frozen performance geometry") {
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.ddrWriteCollectionFlow && !base.ddr.writeCollectionFlow)
            val on = base.copy(ddrWriteCollectionFlow = true)
            assert(on.coreParams == base.coreParams && on.cache == base.cache && on.network == base.network)
            assert(on.ddr.copy(writeCollectionFlow = false) == base.ddr)
            assert(on.name == base.name + "-ddr-write-collection-flow")
        }
        assert(!DdrBridgeConfig.Legacy.writeCollectionFlow && !DdrBridgeConfig.ReadOverlap4.writeCollectionFlow)
        assert(FpgaNextConfig.fromOptions(Set("--selected", "--ddr-write-collection-flow"), true) ==
            FpgaNextConfig.Selected.copy(ddrWriteCollectionFlow = true))
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--ddr-write-collection-flow=false"), true)
        }
    }

    test("capture credits exist only in explicitly selected RAM burst lanes") {
        for (slots <- Seq(1, 4); flow <- Seq(false, true); beats <- Seq(8, 16)) {
            val cfg = DdrBridgeConfig(maxOutstanding = slots, maxBurstBeats = beats,
                maxOutstandingWrites = if (slots == 1) 0 else 2,
                unorderedResponses = slots > 1, writeCollectionFlow = flow)
            cfg.validateSoc()
            val fir = ChiselStage.emitCHIRRTL(new TileLinkAxi4Bridge(
                tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
                axiAddressWidth = 32, axiIdWidth = 4, maxOutstanding = cfg.maxOutstanding,
                maxOutstandingWrites = cfg.maxOutstandingWrites, unorderedResponses = cfg.unorderedResponses,
                maxBurstBeats = cfg.maxBurstBeats, writeCollectionFlow = cfg.writeCollectionFlow,
                axiAddressBase = BigInt("80200000", 16), axiWindowBytes = BigInt(1) << 31))
            assert(fir.contains("writeCaptured") == flow)
            assert(fir.contains("writeSendIndex") == flow)
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new TileLinkAxi4Bridge(writeCollectionFlow = true))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new TileLinkAxi4Bridge(burstEnabled = false, writeCollectionFlow = true,
                axiWindowBytes = 4096))
        }
    }
}
