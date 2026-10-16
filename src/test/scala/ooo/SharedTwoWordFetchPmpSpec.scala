package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class SharedTwoWordFetchPmpSpec extends AnyFunSuite {
    private def hasShared(fir: String): Boolean = fir.contains("module SharedTwoWordFetchPmp :")

    test("two-word helper is combinational and retains full-width bounds and assertions") {
        val fir = ChiselStage.emitCHIRRTL(new SharedTwoWordFetchPmp)
        assert(!fir.contains("reg ") && !fir.contains("regreset "))
        assert(fir.contains("UInt<65>"))
        assert(fir.contains("word PMP requires complete decoded four-byte region granules"))
    }

    test("fetch caller is opt-in and unsupported geometries retain the checker loop") {
        for (entries <- Seq(0, 8, 16); width <- Seq(2, 4); aligned <- Seq(false, true)) {
            val fir = ChiselStage.emitCHIRRTL(new SynchronousFetch(entries, compressed = true,
                cacheSets = 2, fetchWidth = width, alignedFetchPmp = aligned, sharedTwoWordFetchPmp = true))
            assert(hasShared(fir) == (entries == 16 && width == 2 && aligned))
        }
        assert(!hasShared(ChiselStage.emitCHIRRTL(new SynchronousFetch(16, compressed = true,
            cacheSets = 2, alignedFetchPmp = true))))
    }

    test("translation caller requires registered aligned two-word single-page ownership") {
        val baseline = BoardSocConfig.boardParams("staged-fetch-turnover", isa = "rv64gc")
        for (singlePage <- Seq(false, true); entries <- Seq(8, 16)) {
            val p = baseline.copy(alignedFetchSinglePage = singlePage, pmpEntries = entries)
            val fir = ChiselStage.emitCHIRRTL(new InstructionTranslationAdapter(p, sharedTwoWordFetchPmp = true))
            assert(hasShared(fir) == (singlePage && entries == 16))
        }
        assert(!hasShared(ChiselStage.emitCHIRRTL(new InstructionTranslationAdapter(baseline))))
        // Minimal independent configurations avoid unrelated board-profile prerequisites.
        for (width <- Seq(2, 4); aligned <- Seq(false, true); registered <- Seq(false, true)) {
            val p = OooParams(renameWidth = width, machineSystem = true, pmpEntries = 16,
                virtualMemoryLevels = 3, compressedInstructions = true, alignedFetchPmp = aligned,
                registeredTranslationHeads = registered, registeredFabricBoundary = registered,
                registeredTranslatedResponses = registered, parallelHomeQualification = registered,
                independentFetchCapture = registered, flowThroughFetchRequests = registered,
                bufferedFetchRequests = registered)
            assert(!hasShared(ChiselStage.emitCHIRRTL(
                new InstructionTranslationAdapter(p, sharedTwoWordFetchPmp = true))))
        }
    }
}
