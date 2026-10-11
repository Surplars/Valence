package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class LineReadChannelConfigSpec extends AnyFunSuite {
    test("independent line channel preserves shared capacity and CPU configuration") {
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.lineReadChannel)
            val on = base.copy(lineReadChannel = true)
            assert(on.productArity == 47 && !on.registeredPmpRegions && !on.coreParams.registeredPmpRegions &&
                !on.readPrefetchDemandAdoption && !on.cache.readPrefetchDemandAdoption &&
                !on.readPrefetchDirtyRetry && !on.cache.readPrefetchDirtyRetry &&
                !on.splitPrefetchTracking && !on.cache.splitPrefetchTracking &&
                !on.translationHitFlow && on.coreParams == base.coreParams && on.cache == base.cache)
            assert(on.network == base.network && on.ddr == base.ddr.copy(lineReadChannel = true))
            assert(on.ddr.maxOutstanding == 4 && on.ddr.maxOutstandingWrites == 2)
            assert(on.name == base.name + "-line-read-channel")
        }
        assert(FpgaNextConfig.fromOptions(Set("--selected", "--line-read-channel"), true) ==
            FpgaNextConfig.Selected.copy(lineReadChannel = true))
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--line-read-channel=false"), true)
        }
        intercept[IllegalArgumentException] { DdrBridgeConfig(lineReadChannel = true) }
        intercept[IllegalArgumentException] {
            DdrBridgeConfig(maxOutstanding = 4, maxOutstandingWrites = 2, lineReadChannel = true)
        }
    }

    test("real DMA integration selects independent read transport without duplicate fill RAM") {
        val on = ChiselStage.emitCHIRRTL(new DmaPipelineGsim(lineEntries = 4,
            writeCollectionFlow = true, lineTransferDispatchFlow = true, lineReadChannel = true))
        assert(on.contains("module TileLinkAxi4OutstandingBridge"))
        assert(on.contains("lineMemoryRequestValid") && on.contains("lineData") && on.contains("payloadBanks"))
        assert(!on.contains("module TileLinkLineFillEngine"))
    }

    test("official native and GSIM board assemblies connect the new shared DDR ingress") {
        val config = FpgaNextConfig.Selected.copy(ddrWriteCollectionFlow = true,
            lineTransferDispatchFlow = true, lineReadChannel = true,
            experimentalTriSpeedEthernet = true, lsuEntries = 4, dataTranslationEntries = 16,
            dmaLineTransfers = true, dmaLineEntries = 4)
        val native = ChiselStage.emitCHIRRTL(config.managedBoard())
        val gsim = ChiselStage.emitCHIRRTL(FpgaNextBoardGsim.build(config, verifyConfiguration = true))
        for (fir <- Seq(native, gsim)) {
            // InstructionLineCache deliberately keeps its independent TL fill
            // engine. Inspect the DATA-home transfer module, not all of SoC.
            val module = fir.split("  module TileLinkLineTransfer :", 2).lift(1)
                .map(_.split("\n  module ", 2).head).getOrElse("")
            val connected = fir.contains("connect manager.io.lineRead, coherentHome.io.lineRead")
            val direct = module.contains("io.lineRead.request.valid, io.readRequest.valid")
            val duplicatedReader = module.contains("inst reader of TileLinkLineFillEngine")
            assert(connected && direct && !duplicatedReader,
                "official board must wire shared DDR line ingress without duplicate DATA-home read storage")
        }
    }
}
