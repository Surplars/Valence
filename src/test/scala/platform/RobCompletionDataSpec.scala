package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class RobCompletionDataSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2
    private val candidate = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3
    private val ram = Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), 128 * 1024))

    test("completion data banking is exactly one default-off second-batch descendant flag") {
        assert(candidate.config == control.config.copy(bankedRobCompletionData = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(bankedRobCompletionData = true))
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        assert(candidate.name == "full-r1-m3-efficiency-refactor-3")
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        val export = CommonA1RebuildTileArguments.parse(
            Array(candidate.name, "unused-output", "0x80200000", "131072"))
        assert(export._1 == candidate && export._3 == ram)
        intercept[IllegalArgumentException] {
            CommonA1RebuildTileArguments.parse(Array(candidate.name, "unused-output"))
        }
        assert(!OooParams().bankedRobCompletionData && !FpgaNextConfig.Selected.bankedRobCompletionData)
        assert(!CommonCpuProfile.A1.fpga.bankedRobCompletionData)
        for (profile <- CommonA1RebuildProfile.all) {
            val enabled = profile == candidate || profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4 ||
                profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5 ||
                profile == CommonA1RebuildProfile.FullR1M3MulLoadOperandCaptureExperiment ||
                profile == CommonA1RebuildProfile.FullR1M3ContextFetchPrefetchExperiment
            assert(profile.config.bankedRobCompletionData == enabled)
            assert(profile.config.coreParams.bankedRobCompletionData == enabled)
        }
        val p = candidate.config.coreParams
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 && p.recoveryWidth == 4)
        assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
        assert(p.completionTopology == "dual-owner" && p.registeredRobRetirement)
        assert(!p.retirementIntent && !p.retirementSlotIdentity && !p.sharedLane1OwnerMatch)
    }

    test("strict policy and legacy board boundaries do not silently accept the new storage") {
        val policy = candidate.memoryProfile.get
        assert(policy == CommonA1MemoryProfile.ExperimentalEfficiencyRefactor3)
        policy.validate(candidate.config, CommonCpuTilePortParams())
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            intercept[IllegalArgumentException] { policy.validate(old.config, CommonCpuTilePortParams()) }
            old.memoryProfile.foreach { previous =>
                intercept[IllegalArgumentException] { previous.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
        intercept[IllegalArgumentException] { OooParams(bankedRobCompletionData = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(bankedRobCompletionData = true) }
        val p = candidate.config.coreParams
        for (change <- Seq[() => OooParams](
            () => p.copy(robEntries = 32),
            () => p.copy(physicalRegs = 64),
            () => p.copy(tagBits = 32),
            () => p.copy(commitWidth = 1),
            () => p.copy(recoveryWidth = 1),
            () => p.copy(completionTopology = "legacy"),
            () => p.copy(registeredRobRetirement = false),
            () => p.copy(decodedNaturalPmp = false),
            () => p.copy(preparedBareHeadStoreOperands = false))) {
            intercept[IllegalArgumentException] { change() }
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new RenameRob(p, bankedCompletionPayload = true))
        }
    }

    test("payload module declares only writer-owned asynchronous memories and an unreset directory") {
        for (rows <- Seq(4, 8, 16, 32)) {
            val fir = ChiselStage.emitCHIRRTL(new DualWriterRobCompletionData(rows))
            assert(fir.contains("module DualWriterRobCompletionData"))
            assert(fir.contains("latestWriter"))
            assert(!fir.contains("regreset"))
            for (writer <- 0 until 2) {
                for (parity <- 0 until 2) assert(fir.contains(s"completionWriter${writer}Parity$parity"))
                assert(fir.contains(s"tvalWriter$writer"))
            }
        }
        for (rows <- Seq(0, 1, 2, 3, 6, 17)) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new DualWriterRobCompletionData(rows))
            }
        }
    }

    test("the actual third-batch tile accepts only its exact policy and explicit safe range") {
        def emit(config: FpgaNextConfig, policy: Option[CommonA1MemoryProfile],
            ranges: Seq[SideEffectFreeFetchRange]): String =
            ChiselStage.emitCHIRRTL(new CommonA1CpuTile(config,
                memoryProfile = policy, sideEffectFreeFetchRanges = ranges))
        val tile = emit(candidate.config, candidate.memoryProfile, ram)
        assert(tile.contains("module CommonA1CpuTile"))
        assert(tile.contains("module DualWriterRobCompletionData"))
        assert(tile.contains("module RenameRob"))
        assert(!tile.contains("module WriterBankedRobCompletionPayload"))
        intercept[IllegalArgumentException] { emit(candidate.config, None, ram) }
        intercept[IllegalArgumentException] { emit(candidate.config, control.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(control.config, candidate.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(candidate.config, candidate.memoryProfile, Seq.empty) }
        intercept[IllegalArgumentException] {
            emit(candidate.config, candidate.memoryProfile, Seq(SideEffectFreeFetchRange(0, 4096)))
        }
        intercept[IllegalArgumentException] {
            emit(candidate.config.copy(robEntries = Some(32)), candidate.memoryProfile, ram)
        }
    }
}
