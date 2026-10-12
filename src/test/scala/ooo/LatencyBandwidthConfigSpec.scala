package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class LatencyBandwidthConfigSpec extends AnyFunSuite {
    test("explicit latency capacities and DTLB reuse do not silently alter presets") {
        val base = FpgaNextConfig.Selected
        assert(base.productArity == 58 && !base.taggedStoreReturns && !base.pendingReadyStoreBypass && !base.boundHeadStoreOverlap && !base.pendingVirtualStoreProof && !base.frozenStoreProofTransport && base.pendingVirtualStoreProofSlots == 1 && base.pendingStoreEarlyLoadCredits == 1 && !base.publishedPmpChanges && !base.registeredPmpRegions && !base.coreParams.registeredPmpRegions &&
                !base.readPrefetchDemandAdoption && !base.cache.readPrefetchDemandAdoption &&
            !base.readPrefetchDirtyRetry && !base.cache.readPrefetchDirtyRetry &&
            !base.splitPrefetchTracking && !base.cache.splitPrefetchTracking &&
            !base.translationHitFlow && base.dmaLineEntries == 1 && base.ddrOutstanding == 4 &&
            base.ddrWriteCredits == 2 && !base.dataTlbWriteReadReuse)
        val selected = FpgaNextConfig.fromOptions(Set("--selected", "--dma-line-transfers",
            "--dma-line-entries=8", "--ddr-outstanding=8", "--ddr-write-credits=4",
            "--dtlb-write-read-reuse"), true)
        assert(selected == base.copy(dmaLineTransfers = true, dmaLineEntries = 8,
            ddrOutstanding = 8, ddrWriteCredits = 4, dataTlbWriteReadReuse = true))
        assert(selected.coreParams == base.coreParams && selected.cache == base.cache && selected.network == base.network)
        assert(selected.ddr == base.ddr.copy(maxOutstanding = 8, maxOutstandingWrites = 4))
        assert(selected.name.endsWith("-dma-lines-owners8-ddr8w4-dtlb-write-read-reuse"))
        for (bad <- Seq("--ddr-outstanding=16", "--ddr-write-credits=8", "--dtlb-write-read-reuse=false")) {
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set("--selected", bad), true) }
        }
        intercept[IllegalArgumentException] { base.copy(dmaLineEntries = 8) }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--selected", "--ddr-outstanding=4", "--ddr-outstanding=8"), true)
        }
    }

    test("eight tagged DMA owners and four writes elaborate through the real coherent path") {
        val fir = ChiselStage.emitCHIRRTL(new DmaPipelineGsim(lineEntries = 8,
            writeCollectionFlow = true, lineTransferDispatchFlow = true, lineReadChannel = true,
            ddrSlots = 8, ddrWrites = 4))
        val tags = fir.contains("homeLineRequestTag : UInt<3>") && fir.contains("lineResponseOfferTag : UInt<3>")
        assert(tags && fir.contains("module AtomicMemory") && fir.contains("module MixedCoherentLineHome"),
            "real DMA/coherence integration must retain all eight tag values")
    }

    test("native and GSIM official assembly forward the D-only translation policy") {
        val config = FpgaNextConfig.Selected.copy(dataTlbWriteReadReuse = true,
            experimentalTriSpeedEthernet = true, lsuEntries = 4, dataTranslationEntries = 16,
            dmaLineTransfers = true, dmaLineEntries = 4)
        val native = ChiselStage.emitCHIRRTL(config.managedBoard())
        val simulated = ChiselStage.emitCHIRRTL(FpgaNextBoardGsim.build(config, verifyConfiguration = true))
        for (fir <- Seq(native, simulated)) {
            // Extra coalescing network is absent in the I-service; two distinct
            // definitions demonstrate that the D-only flag reached production.
            val count = "  module SvTranslationService".r.findAllIn(fir).length
            assert(count == 2 && fir.contains("matching"),
                "both official assemblies must carry the DTLB permission policy")
        }
    }
}
