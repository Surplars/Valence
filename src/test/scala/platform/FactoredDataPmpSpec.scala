package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class FactoredDataPmpSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProof
    private val candidate = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofFactoredPmp
    test("factored generic PMP is one default-off flag on the old elastic topology") {
        assert(!OooParams().factoredDataPmpRange && !FpgaNextConfig.Selected.factoredDataPmpRange)
        assert(!CommonCpuProfile.A1.fpga.factoredDataPmpRange)
        assert(candidate.config == control.config.copy(factoredDataPmpRange = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(factoredDataPmpRange = true))
        assert(candidate.config.translationHitFlow && candidate.config.combinedCheckedDataFlow)
        assert(!candidate.config.registeredDataTranslation && !candidate.config.registeredRawCertifiedFlow)
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        candidate.memoryProfile.get.validate(candidate.config, CommonCpuTilePortParams())
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            assert(!old.config.factoredDataPmpRange)
            old.memoryProfile.foreach { policy =>
                intercept[IllegalArgumentException] { policy.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] { candidate.memoryProfile.get.validate(control.config, CommonCpuTilePortParams()) }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
    }
    test("generic factoring cannot silently adopt an aligned specialization") {
        for (entries <- Seq(0, 8, 16)) {
            def emit(p: => PmpChecker): String = ChiselStage.emitCHIRRTL(p)
            val zero = emit(new PmpChecker(entries, factoredGenericRanges = true, exportDecision = true))
            assert(zero.contains("PmpGenericRangeComparisons") == (entries != 0))
            intercept[IllegalArgumentException] { emit(new PmpChecker(entries, alignedWordAccess = true, factoredGenericRanges = true)) }
            intercept[IllegalArgumentException] { emit(new PmpChecker(entries, naturalAlignedAccess = true, factoredGenericRanges = true)) }
            intercept[IllegalArgumentException] { emit(new PmpChecker(entries, alignedLineAccess = true, factoredGenericRanges = true)) }
            intercept[IllegalArgumentException] { emit(new PmpChecker(entries, decodedWordGranularity = true, factoredGenericRanges = true)) }
            intercept[IllegalArgumentException] { emit(new PmpChecker(entries, sharedAlignedBounds = true, factoredGenericRanges = true)) }
        }
    }
    test("only the explicit legacy main data checker selects factoring") {
        def emit(profile: CommonA1RebuildProfile): String = ChiselStage.emitCHIRRTL(
            new DataTranslationAdapter(profile.config.coreParams, registerCheckedRequests = true,
                translationHitFlow = profile.config.translationHitFlow))
        assert(!emit(control).contains("PmpGenericRangeComparisons"))
        val fir = emit(candidate)
        assert(fir.contains("PmpGenericRangeComparisons") && !fir.contains("DataPhysicalPermissionEvaluator"))
        assert(!emit(CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofRegisteredRaw)
            .contains("PmpGenericRangeComparisons"))
    }
}
