package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import chisel3._
import soc.core.ooo._
import soc.platform._

/** Configuration and interface contracts only; behavioral safety requires the separate GSIM oracle. */
class ContextFetchPrefetchSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4
    private val candidate = CommonA1RebuildProfile.FullR1M3ContextFetchPrefetchExperiment
    private val ram = Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), 128 * 1024))

    test("context prefetch is one explicit default-off fourth-baseline flag without added demand credits") {
        assert(candidate.config == control.config.copy(contextOwnedInstructionPrefetch = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(contextOwnedInstructionPrefetch = true))
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        assert(!OooParams().contextOwnedInstructionPrefetch && !FpgaNextConfig.Selected.contextOwnedInstructionPrefetch)
        assert(!CommonCpuProfile.A1.fpga.contextOwnedInstructionPrefetch)
        for (profile <- CommonA1RebuildProfile.all) {
            assert(profile.config.contextOwnedInstructionPrefetch == (profile == candidate))
            assert(profile.config.coreParams.contextOwnedInstructionPrefetch == (profile == candidate))
        }
        assert(!candidate.config.loadPayloadNomination && !candidate.config.coreParams.loadPayloadNomination)
        assert(!CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5.config.contextOwnedInstructionPrefetch)
        val p = candidate.config.coreParams
        assert(candidate.config.fetchTransactionSlots == 2 && p.tagBits == 64)
        assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
        assert(p.fpEnabled && p.fpConfig.memory && p.pmpEntries == 16 && p.virtualMemoryLevels == 3)
    }

    test("new policy rejects old profiles and old policies reject the new flag") {
        val policy = candidate.memoryProfile.get
        assert(policy == CommonA1MemoryProfile.ExperimentalContextFetchPrefetch)
        policy.validate(candidate.config, CommonCpuTilePortParams())
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            intercept[IllegalArgumentException] { policy.validate(old.config, CommonCpuTilePortParams()) }
            old.memoryProfile.foreach { previous =>
                intercept[IllegalArgumentException] { previous.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] { OooParams(contextOwnedInstructionPrefetch = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(contextOwnedInstructionPrefetch = true) }
        intercept[IllegalArgumentException] { candidate.config.copy(fetchThirdPacketLookahead = false) }
        intercept[IllegalArgumentException] { candidate.config.coreParams.copy(registeredFetchPacket = false) }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
    }

    test("physical context preserves the old two-bit ABI and adds full source identity only when enabled") {
        class ContextWidthFixture extends Module {
            val old = IO(Input(new PhysicalFetchRequestContext()))
            val fresh = IO(Input(new PhysicalFetchRequestContext(withSpeculationContext = true)))
            require(old.getWidth == 2 && old.sourceSequence.isEmpty && old.identityTranslation.isEmpty)
            require(fresh.getWidth == 67 && fresh.privilege.getWidth == 2)
            require(fresh.sourceSequence.get.getWidth == 64 && fresh.identityTranslation.get.getWidth == 1)
        }
        ChiselStage.emitCHIRRTL(new ContextWidthFixture)
    }

    test("raw correction observer exists only with the optional prefetch feature") {
        def emit(enabled: Boolean): String = ChiselStage.emitCHIRRTL(new RegisteredFetchPacket(
            2, true, BigInt("80200000", 16), parallelValidation = true,
            acceptedPrefixValidation = true, circularPayload = true,
            contextOwnedInstructionPrefetch = enabled))
        assert(!emit(false).contains("speculationCancel"))
        assert(emit(true).contains("speculationCancel"))
    }

    test("actual tile connects optional cancellation and full-drain controls with explicit RAM policy") {
        def emit(config: FpgaNextConfig, policy: Option[CommonA1MemoryProfile],
            ranges: Seq[SideEffectFreeFetchRange]): String =
            ChiselStage.emitCHIRRTL(new CommonA1CpuTile(config,
                memoryProfile = policy, sideEffectFreeFetchRanges = ranges))
        val old = emit(control.config, control.memoryProfile, ram)
        assert(!old.contains("fetchSpeculationCancel") && !old.contains("speculationMinimumSequence"))
        val fresh = emit(candidate.config, candidate.memoryProfile, ram)
        assert(fresh.contains("fetchSpeculationCancel") && fresh.contains("speculationMinimumSequence"))
        assert(fresh.contains("speculationDrained") && fresh.contains("speculationAgeUsable"))
        intercept[IllegalArgumentException] { emit(candidate.config, None, ram) }
        intercept[IllegalArgumentException] { emit(candidate.config, control.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(control.config, candidate.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(candidate.config, candidate.memoryProfile, Seq.empty) }
        intercept[IllegalArgumentException] {
            emit(candidate.config, candidate.memoryProfile, Seq(SideEffectFreeFetchRange(0, 4096)))
        }
    }
}
