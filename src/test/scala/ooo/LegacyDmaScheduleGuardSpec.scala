package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.FpgaNextConfig

/** Unsupported legacy routes must reject, never silently drop the optional DMA policy. */
class LegacyDmaScheduleGuardSpec extends AnyFunSuite {
    test("both opt-in policies are rejected before each unqualified board fixture is constructed") {
        val configs = Seq(
            FpgaNextConfig.Selected.copy(dmaLineTransfers = true, dmaLineThresholdRewrite = true),
            FpgaNextConfig.Selected.copy(dmaLineTransfers = true, dmaLineEntries = 2, dmaSingleReadWait = true)
        )
        def rejected(body: => Any): Unit = {
            val error = intercept[IllegalArgumentException] { body }
            assert(error.getMessage.contains("DMA schedule experiments require CommonFabricDmaScheduleGsimMain"))
        }
        configs.foreach { config =>
            rejected(FpgaNextBoardGsim.build(config))
            rejected(CanonicalOverlapBoardBuild.build(config, overlap = false))
            rejected(ChiselStage.emitCHIRRTL(new MatchingManagedBoard(config)))
        }
    }

    test("native export options do not advertise unqualified DMA scheduling flags") {
        for (flag <- Seq("--dma-line-threshold-rewrite", "--dma-single-read-wait")) {
            assert(!FpgaNextProfileOptions.allowed.contains(flag))
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(flag)) }
        }
    }
}
