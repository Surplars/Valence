package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.FpgaNextConfig
import soc.ip.dma.MemoryCopyDma

class CommonFabricDmaScheduleSpec extends AnyFunSuite {
    test("all production presets and omitted options keep both DMA changes off") {
        for (preset <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate,
            FpgaNextConfig.ControlCandidate, FpgaNextConfig.Selected)) {
            assert(!preset.dmaLineThresholdRewrite && !preset.dmaSingleReadWait)
        }
        assert(FpgaNextConfig.fromOptions(Set.empty, defaultSelected = true) == FpgaNextConfig.Selected)
        assert(CommonFabricDmaSchedule.config("default") == FpgaNextConfig.Selected)
    }

    test("source controls preserve every omitted dimension and name both choices") {
        val base = FpgaNextConfig.Selected.copy(dmaLineTransfers = true, dmaLineEntries = 2)
        val enabled = FpgaNextConfig.fromOptions(Set("--selected", "--dma-line-transfers", "--dma-line-entries=2",
            "--dma-line-threshold-rewrite", "--dma-single-read-wait"), defaultSelected = true)
        assert(enabled.copy(dmaLineThresholdRewrite = false, dmaSingleReadWait = false) == base)
        assert(enabled.coreParams == base.coreParams && enabled.ddr == base.ddr && enabled.cache == base.cache)
        assert(enabled.name == base.name + "-dma-line-threshold-dma-single-read-wait")
        assert(base.copy(dmaLineThresholdRewrite = true).dmaLineThresholdRewrite)
        assert(base.copy(dmaSingleReadWait = true).dmaSingleReadWait)
    }

    test("the scheduling bound cannot silently select an unqualified tag count") {
        for (depth <- Seq(1, 4, 8)) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig(dmaLineTransfers = true, dmaLineEntries = depth, dmaSingleReadWait = true)
            }
        }
        intercept[IllegalArgumentException] { FpgaNextConfig(dmaLineThresholdRewrite = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(dmaSingleReadWait = true) }
        for (flag <- Seq("--dma-line-threshold-rewrite", "--dma-single-read-wait")) {
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set(flag + "=true"), true) }
        }
        intercept[IllegalArgumentException] { CommonFabricDmaSchedule.config("unknown") }
    }

    test("matched fabric modes retain the DDR pool and CPU cache geometry") {
        val base = FpgaNextConfig.Selected
        for (mode <- CommonFabricDmaSchedule.modes) {
            val config = CommonFabricDmaSchedule.config(mode)
            assert(config.coreParams == base.coreParams && config.cache == base.cache)
            assert(config.ddr.maxOutstanding == 4 && config.ddr.maxOutstandingWrites == 2)
            assert(config.ddr.maxBurstBeats == 16 && config.dmaLineYieldCycles == 0)
            assert(config.copy(ddrWriteCollectionFlow = base.ddrWriteCollectionFlow,
                dmaLineTransfers = base.dmaLineTransfers, dmaLineEntries = base.dmaLineEntries,
                lineReadChannel = base.lineReadChannel, dmaLineThresholdRewrite = false,
                dmaSingleReadWait = false) == base)
        }
        val previous = CommonFabricDmaSchedule.config("dual")
        assert(CommonFabricDmaSchedule.config("read-window").copy(dmaSingleReadWait = false) == previous)
    }

    test("DMA constructor guards agree with config and default hardware has no read admission gate") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MemoryCopyDma(singleReadWait = true)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MemoryCopyDma(lineThresholdRewrite = true)) }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MemoryCopyDma(lineTransfers = true, lineEntries = 4, singleReadWait = true))
        }
        val off = ChiselStage.emitCHIRRTL(new MemoryCopyDma(lineTransfers = true, lineEntries = 2))
        val on = ChiselStage.emitCHIRRTL(new MemoryCopyDma(lineTransfers = true, lineEntries = 2,
            lineThresholdRewrite = true, singleReadWait = true))
        assert(!off.contains("node readInFlight =") && on.contains("node readInFlight ="))
        for (fir <- Seq(off, on)) {
            assert(fir.contains("payloads : UInt<512>[2]"))
            assert(fir.contains("pipelined DMA response has no retained owner"))
            assert(fir.contains("pipelined line crossed scalar DMA ownership"))
        }
    }
}
