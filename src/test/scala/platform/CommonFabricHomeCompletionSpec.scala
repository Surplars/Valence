package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.MixedCoherentLineHome

class CommonFabricHomeCompletionSpec extends AnyFunSuite {
    test("completion flow selects only the unchanged dual-read two-tag control") {
        val config = CommonFabricHomeCompletion.config
        assert(config == CommonFabricDmaSchedule.config("dual"))
        assert(config.dmaLineTransfers && config.dmaLineEntries == 2 && !config.dmaSingleReadWait)
        assert(config.ddr.maxOutstanding == 4 && config.ddr.maxOutstandingWrites == 2)
        assert(!CommonFabricHomeCompletion.enabled("off") && CommonFabricHomeCompletion.enabled("on"))
        intercept[IllegalArgumentException] { CommonFabricHomeCompletion.enabled("unknown") }
    }

    test("Home rejects completion flow outside the two-tag line path") {
        for (depth <- Seq(1, 4, 8)) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new MixedCoherentLineHome(dmaLineTransfers = true,
                    dmaLineEntries = depth, dmaMaintenanceCompletionFlow = true))
            }
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MixedCoherentLineHome(dmaMaintenanceCompletionFlow = true))
        }
    }

    test("both modes retain original dispatch and ownership checks") {
        for (enabled <- Seq(false, true)) {
            val fir = ChiselStage.emitCHIRRTL(new MixedCoherentLineHome(trackedLines = 4,
                dmaLineTransfers = true, dmaLineEntries = 2, dmaMaintenanceCompletionFlow = enabled))
            assert(fir.contains("CoherentWriteDispatch"))
            assert(fir.contains("home line tag reused before response"))
            assert(fir.contains("home line response lost read/write owner"))
            assert(fir.contains("coherent home backing rejected dirty writeback"))
            assert(fir.contains("DMA write tag overlaps release/probe tag class"))
            assert(fir.contains("DMA maintenance completion lost its retained exclusive owner") == enabled)
        }
    }
}
