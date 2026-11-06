package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.MixedCoherentLineHome

class CommonFabricDmaProbeAcquireSpec extends AnyFunSuite {
    private def emit(enabled: Boolean, readOverlap: Boolean = true, clients: Int = 2, tags: Int = 2,
        lines: Int = 1024, ways: Int = 4, acquires: Int = 2, writebacks: Int = 2,
        readChannel: Boolean = true, lineGrant: Boolean = true, completionFlow: Boolean = true): String =
        ChiselStage.emitCHIRRTL(new MixedCoherentLineHome(bytes = BigInt(2) * 1024 * 1024 * 1024,
            trackedLines = lines, trackedWays = ways, acquireEntries = acquires, writebackEntries = writebacks,
            mixedReadWrite = true, dmaLineTransfers = true, dmaLineEntries = tags,
            lineReadChannel = readChannel, internalLineGrant = lineGrant, nClients = clients,
            dmaMaintenanceCompletionFlow = completionFlow, dmaReadAcquireOverlap = readOverlap,
            dmaProbeAcquireOverlap = enabled))

    test("staged DMA Probe overlap preserves baseline geometry and owner assertions") {
        val config = CommonFabricHomeCompletion.config
        assert(config.dmaLineTransfers && config.dmaLineEntries == 2 && !config.dmaSingleReadWait)
        assert(config.ddr.maxOutstanding == 4 && config.ddr.maxOutstandingWrites == 2)
        for (enabled <- Seq(false, true)) {
            val fir = emit(enabled)
            for (message <- Seq("home line tag reused before response", "home refill result has no acquire owner",
                "coherent home backing rejected dirty writeback", "dirty probe data must not be corrupt",
                "DMA read tag overlaps refill tag class", "DMA write tag overlaps release/probe tag class",
                "DMA and Acquire must retain exclusive admission arbitration",
                "stalled direct read must remain irrevocable", "maintenance crossed active acquire/release")) {
                assert(fir.contains(message))
            }
            assert(fir.contains("progressed DMA maintenance shares an Acquire set") == enabled)
            assert(fir.contains("dispatched DMA and Acquire own the same physical line") == enabled)
            assert(fir.contains("staged DMA read lost its retained owner or overwrote a queued fill") == enabled)
            assert(fir.contains("staged DMA maintenance lost its pending tag") == enabled)
            assert(fir.contains("fresh Acquire crossed a live DMA write") == enabled)
            assert(fir.contains("DMA write crossed an Acquire owner") == !enabled)
            assert(fir.contains("DMA read/Acquire overlap crossed maintenance ownership") == !enabled)
        }
    }

    test("staged DMA Probe overlap requires the bounded existing read-overlap profile") {
        intercept[IllegalArgumentException] { emit(true, readOverlap = false) }
        intercept[IllegalArgumentException] { emit(true, clients = 1) }
        intercept[IllegalArgumentException] { emit(true, tags = 4) }
        intercept[IllegalArgumentException] { emit(true, lines = 512) }
        intercept[IllegalArgumentException] { emit(true, ways = 2) }
        intercept[IllegalArgumentException] { emit(true, acquires = 4) }
        intercept[IllegalArgumentException] { emit(true, writebacks = 1) }
        intercept[IllegalArgumentException] { emit(true, readChannel = false) }
        intercept[IllegalArgumentException] { emit(true, lineGrant = false) }
    }

    test("staged DMA read arbitration also elaborates without completion-edge flow") {
        val fir = emit(true, completionFlow = false)
        assert(fir.contains("staged DMA read lost its retained owner or overwrote a queued fill"))
        assert(!fir.contains("DMA maintenance completion lost its retained exclusive owner"))
    }
}
