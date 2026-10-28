package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class DecodedNaturalPmpSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor
    private val candidate = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2

    test("typed PMP is an explicit first-batch descendant with no old-profile change") {
        assert(candidate.config == control.config.copy(decodedNaturalPmp = true, preparedBareHeadStoreOperands = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(decodedNaturalPmp = true, preparedBareHeadStoreOperands = true))
        for (profile <- CommonA1RebuildProfile.all) {
            val enabled = profile == candidate || profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3 ||
                profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4 ||
                profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5 ||
                profile == CommonA1RebuildProfile.FullR1M3MulLoadOperandCaptureExperiment ||
                profile == CommonA1RebuildProfile.FullR1M3ContextFetchPrefetchExperiment
            assert(profile.config.decodedNaturalPmp == enabled)
            assert(profile.config.coreParams.decodedNaturalPmp == enabled)
            assert(profile.config.preparedBareHeadStoreOperands == enabled)
            assert(profile.config.coreParams.preparedBareHeadStoreOperands == enabled)
        }
        assert(!OooParams().decodedNaturalPmp && !FpgaNextConfig.Selected.decodedNaturalPmp)
        assert(!OooParams().preparedBareHeadStoreOperands && !FpgaNextConfig.Selected.preparedBareHeadStoreOperands)
        // The relation specialization has its own contract, not a dependency on the performance flag.
        assert(!control.config.copy(decodedNaturalPmp = true).coreParams.preparedBareHeadStoreOperands)
        assert(!control.config.copy(preparedBareHeadStoreOperands = true).coreParams.decodedNaturalPmp)
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        candidate.memoryProfile.get.validate(candidate.config, CommonCpuTilePortParams())
        intercept[IllegalArgumentException] { control.memoryProfile.get.validate(candidate.config, CommonCpuTilePortParams()) }
        intercept[IllegalArgumentException] { candidate.memoryProfile.get.validate(control.config, CommonCpuTilePortParams()) }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
    }

    test("the capability cannot leak into an unqualified physical authority topology") {
        intercept[IllegalArgumentException] { OooParams(decodedNaturalPmp = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(decodedNaturalPmp = true) }
        val p = candidate.config.coreParams
        assert(!p.registeredPmpRegions) // Current A1 decodes combinationally from raw CSR registers.
        assert(p.copy(registeredPmpRegions = true).decodedNaturalPmp) // Same typed invariant for the optional producer.
        for (change <- Seq[() => OooParams](
            () => p.copy(machineSystem = false),
            () => p.copy(sharedLoadProofPmpBounds = false),
            () => p.copy(sourceLocalLoadProofCancellation = false),
            () => p.copy(pmpEntries = 8))) {
            intercept[IllegalArgumentException] { change() }
        }
    }

    test("typed natural checker is combinational, retaining separate generic contracts") {
        for (entries <- Seq(0, 8, 16)) {
            val typed = ChiselStage.emitCHIRRTL(new DecodedNaturalPmpChecker(entries, exportDecision = true))
            assert(typed.contains("decoded natural PMP requires an aligned access of at most eight bytes"))
            assert(!typed.linesIterator.exists(_.trim.startsWith("reg ")))
            val generic = ChiselStage.emitCHIRRTL(new PmpChecker(entries, naturalAlignedAccess = true,
                sharedAlignedBounds = true, exportDecision = true))
            assert(generic.contains("natural PMP checker requires an aligned access of at most eight bytes"))
            assert(!generic.contains("DecodedPmpGranuleState"))
        }
    }

    test("the actual second-batch CPU tile accepts only its explicit policy and safe fetch ranges") {
        val ram = Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), 128 * 1024))
        def emit(policy: Option[CommonA1MemoryProfile], ranges: Seq[SideEffectFreeFetchRange]): String =
            ChiselStage.emitCHIRRTL(new CommonA1CpuTile(candidate.config,
                memoryProfile = policy, sideEffectFreeFetchRanges = ranges))
        // Configuration-only checks cannot detect a forgotten policy whitelist
        // inside the actual tile. Elaborate the production descendant itself.
        val tile = emit(candidate.memoryProfile, ram)
        assert(tile.contains("module CommonA1CpuTile"))
        assert(tile.contains("module DecodedNaturalPmpChecker"))
        assert(tile.contains("module IntegerBackend"))
        intercept[IllegalArgumentException] { emit(None, ram) }
        intercept[IllegalArgumentException] { emit(control.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(candidate.memoryProfile, Seq.empty) }
        intercept[IllegalArgumentException] {
            emit(candidate.memoryProfile, Seq(SideEffectFreeFetchRange(0, 4096)))
        }
    }
}
