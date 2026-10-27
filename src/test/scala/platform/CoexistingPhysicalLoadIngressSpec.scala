package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class CoexistingPhysicalLoadIngressSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3
    private val candidate = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4
    private val ram = Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), 128 * 1024))

    test("coexisting ordinary ingress is exactly one default-off third-batch descendant flag") {
        assert(candidate.config == control.config.copy(coexistingPhysicalLoadIngress = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(coexistingPhysicalLoadIngress = true))
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        assert(candidate.name == "full-r1-m3-efficiency-refactor-4")
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        assert(!OooParams().coexistingPhysicalLoadIngress && !FpgaNextConfig.Selected.coexistingPhysicalLoadIngress)
        assert(!CommonCpuProfile.A1.fpga.coexistingPhysicalLoadIngress)
        for (profile <- CommonA1RebuildProfile.all) {
            val enabled = profile == candidate || profile == CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5
            assert(profile.config.coexistingPhysicalLoadIngress == enabled)
            assert(profile.config.coreParams.coexistingPhysicalLoadIngress == enabled)
        }
        val p = candidate.config.coreParams
        assert(!p.physicalLoadIngressFlow && p.certifiedLoadIngress && p.bankedRobCompletionData)
        assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2 && p.tagBits == 64)
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.storeBufferEntries == 2)
        assert(p.fpEnabled && p.fpConfig.memory && p.pmpEntries == 16 && p.virtualMemoryLevels == 3)
        assert(!p.fastHeadLoadRetire && !p.loadCompletionBypass && !p.registeredLoadResultReady)
    }

    test("new policy is exact and cannot leak into old policy or legacy board boundaries") {
        val policy = candidate.memoryProfile.get
        assert(policy == CommonA1MemoryProfile.ExperimentalEfficiencyRefactor4)
        policy.validate(candidate.config, CommonCpuTilePortParams())
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            intercept[IllegalArgumentException] { policy.validate(old.config, CommonCpuTilePortParams()) }
            old.memoryProfile.foreach { previous =>
                intercept[IllegalArgumentException] { previous.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
        val export = CommonA1RebuildTileArguments.parse(
            Array(candidate.name, "unused-output", "0x80200000", "131072"))
        assert(export._1 == candidate && export._3 == ram)
        intercept[IllegalArgumentException] {
            CommonA1RebuildTileArguments.parse(Array(candidate.name, "unused-output"))
        }
    }

    test("ordinary coexistence cannot remove registered producer or certified authorization prerequisites") {
        intercept[IllegalArgumentException] { OooParams(coexistingPhysicalLoadIngress = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(coexistingPhysicalLoadIngress = true) }
        val p = candidate.config.coreParams
        for (change <- Seq[() => OooParams](
            () => p.copy(bankedRobCompletionData = false),
            () => p.copy(certifiedLoadIngress = false),
            () => p.copy(identityDataRequestFlow = false),
            () => p.copy(bufferedRamStores = false),
            () => p.copy(registeredMemoryRequests = false),
            () => p.copy(registeredTranslationHeads = false),
            () => p.copy(physicalLoadIngressFlow = true),
            () => p.copy(registeredDataTranslation = true),
            () => p.copy(registeredRawCertifiedFlow = true),
            () => p.copy(tagBits = 32),
            () => p.copy(memoryEntries = 8))) {
            intercept[IllegalArgumentException] { change() }
        }
        // The older mutually exclusive feature is still forbidden, not silently repurposed.
        intercept[IllegalArgumentException] { control.config.copy(physicalLoadIngressFlow = true).coreParams }
    }

    test("actual adapter elaborates coexistence only with its certified non-flow checked boundary") {
        def adapter(p: OooParams, certified: Boolean, checked: Boolean = true): DataTranslationAdapter =
            new DataTranslationAdapter(p, registerCheckedRequests = checked, translationHitFlow = true,
                alignedNextLinePmp = p.alignedNextLinePmp, factorCheckedNextAllowed = p.factorCheckedNextAllowed,
                certifiedLoadIngress = certified)
        val oldFir = ChiselStage.emitCHIRRTL(adapter(control.config.coreParams, true))
        val newFir = ChiselStage.emitCHIRRTL(adapter(candidate.config.coreParams, true))
        assert(!oldFir.contains("ordinary registered ingress transfers one exact request"))
        assert(newFir.contains("ordinary registered ingress transfers one exact request"))
        assert(newFir.contains("blocked ordinary ingress spills once"))
        assert(newFir.contains("certified ingress transfers the exact final-port load"))
        assert(newFir.contains("module TwoEntryRegisterQueue"))
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(adapter(candidate.config.coreParams, false))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(adapter(candidate.config.coreParams, true, false))
        }
    }

    test("the actual fourth tile retains its exact policy, safe fetch range and complete producer integration") {
        def emit(config: FpgaNextConfig, policy: Option[CommonA1MemoryProfile],
            ranges: Seq[SideEffectFreeFetchRange]): String =
            ChiselStage.emitCHIRRTL(new CommonA1CpuTile(config,
                memoryProfile = policy, sideEffectFreeFetchRanges = ranges))
        val tile = emit(candidate.config, candidate.memoryProfile, ram)
        assert(tile.contains("module CommonA1CpuTile"))
        assert(tile.contains("module FloatingPointMemoryPipeline"))
        assert(tile.contains("module RegisteredRequestQueue"))
        assert(tile.contains("module DualWriterRobCompletionData"))
        assert(tile.contains("ordinary registered ingress transfers one exact request"))
        intercept[IllegalArgumentException] { emit(candidate.config, None, ram) }
        intercept[IllegalArgumentException] { emit(candidate.config, control.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(control.config, candidate.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(candidate.config, candidate.memoryProfile, Seq.empty) }
    }
}
