package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.MixedCoherentLineHome

class CommonFabricDmaAcquireSpec extends AnyFunSuite {
    private def emit(enabled: Boolean, clients: Int = 2, tags: Int = 2, lines: Int = 1024,
        ways: Int = 4, readChannel: Boolean = true): String =
        ChiselStage.emitCHIRRTL(new MixedCoherentLineHome(bytes = BigInt(2) * 1024 * 1024 * 1024,
            trackedLines = lines, trackedWays = ways, acquireEntries = 2, writebackEntries = 2,
            mixedReadWrite = true, dmaLineTransfers = true, dmaLineEntries = tags,
            lineReadChannel = readChannel, internalLineGrant = true, nClients = clients,
            dmaMaintenanceCompletionFlow = true, dmaReadAcquireOverlap = enabled))

    test("DMA-read Acquire overlap preserves the selected geometry and defaults") {
        val config = CommonFabricHomeCompletion.config
        assert(config.dmaLineTransfers && config.dmaLineEntries == 2 && !config.dmaSingleReadWait)
        assert(config.ddr.maxOutstanding == 4 && config.ddr.maxOutstandingWrites == 2)
        for (enabled <- Seq(false, true)) {
            val fir = emit(enabled)
            assert(fir.contains("home line tag reused before response"))
            assert(fir.contains("home refill result has no acquire owner"))
            assert(fir.contains("coherent home backing rejected dirty writeback"))
            assert(fir.contains("DMA read tag overlaps refill tag class"))
            assert(fir.contains("DMA read and Acquire own the same physical line") == enabled)
            assert(fir.contains("DMA and Acquire must retain exclusive admission arbitration") == enabled)
            assert(fir.contains("live DMA line crossed refill or scalar owner") == !enabled)
        }
    }

    test("DMA-read Acquire overlap rejects unqualified profiles") {
        intercept[IllegalArgumentException] { emit(true, clients = 1) }
        intercept[IllegalArgumentException] { emit(true, tags = 4) }
        intercept[IllegalArgumentException] { emit(true, lines = 512) }
        intercept[IllegalArgumentException] { emit(true, ways = 2) }
        intercept[IllegalArgumentException] { emit(true, readChannel = false) }
    }
}
