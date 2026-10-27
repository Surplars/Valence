package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

/** Configuration/elaboration only. Runtime payload selection has a separate independent GSIM oracle. */
class LoadPayloadNominationSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4
    private val candidate = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5
    private val ram = Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), 128 * 1024))

    test("fifth profile changes only default-off load payload nomination") {
        assert(candidate.config == control.config.copy(loadPayloadNomination = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(loadPayloadNomination = true))
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        assert(candidate.name == "full-r1-m3-efficiency-refactor-5")
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        assert(!OooParams().loadPayloadNomination && !FpgaNextConfig().loadPayloadNomination)
        assert(!FpgaNextConfig.Selected.loadPayloadNomination && !CommonCpuProfile.A1.fpga.loadPayloadNomination)
        for (profile <- CommonA1RebuildProfile.all) {
            assert(profile.config.loadPayloadNomination == (profile == candidate))
            assert(profile.config.coreParams.loadPayloadNomination == (profile == candidate))
        }
        val p = candidate.config.coreParams
        assert(p.coexistingPhysicalLoadIngress && p.certifiedLoadIngress && p.bankedRobCompletionData)
        assert(p.guardedNaturalDataPmp && p.combinedCheckedDataFlow && p.precheckedDataRequestFlow)
        assert(p.registeredTranslationHeads && p.registeredMemoryRequests && p.registeredTranslatedResponses)
        assert(!p.physicalLoadIngressFlow && !p.registeredDataTranslation && !p.registeredRawCertifiedFlow)
        assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2 && p.tagBits == 64)
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.storeBufferEntries == 2)
        assert(p.fpEnabled && p.fpConfig.memory && p.pmpEntries == 16 && p.virtualMemoryLevels == 3)
        assert(!p.fastHeadLoadRetire && !p.loadCompletionBypass && !p.registeredLoadResultReady)
    }

    test("fifth policy is exact and cannot silently enter any old policy or legacy board factory") {
        val policy = candidate.memoryProfile.get
        assert(policy == CommonA1MemoryProfile.ExperimentalEfficiencyRefactor5)
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

    test("nomination cannot weaken fourth topology, legacy exclusions or full owner widths") {
        intercept[IllegalArgumentException] { OooParams(loadPayloadNomination = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(loadPayloadNomination = true) }
        val p = candidate.config.coreParams
        for (change <- Seq[() => OooParams](
            () => p.copy(coexistingPhysicalLoadIngress = false),
            () => p.copy(certifiedLoadIngress = false),
            () => p.copy(bankedRobCompletionData = false),
            () => p.copy(guardedNaturalDataPmp = false),
            () => p.copy(combinedCheckedDataFlow = false),
            () => p.copy(precheckedDataRequestFlow = false),
            () => p.copy(identityDataRequestFlow = false),
            () => p.copy(bufferedRamStores = false),
            () => p.copy(registeredMemoryRequests = false),
            () => p.copy(registeredTranslationHeads = false),
            () => p.copy(registeredTranslatedResponses = false),
            () => p.copy(physicalLoadIngressFlow = true),
            () => p.copy(registeredDataTranslation = true),
            () => p.copy(registeredRawCertifiedFlow = true),
            () => p.copy(renameWidth = 1),
            () => p.copy(completionWidth = 1),
            () => p.copy(commitWidth = 1),
            () => p.copy(tagBits = 32),
            () => p.copy(memoryEntries = 8))) {
            intercept[IllegalArgumentException] { change() }
        }
        val c = candidate.config
        for (change <- Seq[() => FpgaNextConfig](
            () => c.copy(coexistingPhysicalLoadIngress = false),
            () => c.copy(certifiedLoadIngress = false),
            () => c.copy(bankedRobCompletionData = false),
            () => c.copy(combinedCheckedDataFlow = false),
            () => c.copy(translationHitFlow = false),
            () => c.copy(physicalLoadIngressFlow = true),
            () => c.copy(registeredDataTranslation = true),
            () => c.copy(registeredRawCertifiedFlow = true))) {
            intercept[IllegalArgumentException] { change().coreParams }
        }
        intercept[IllegalArgumentException] { control.config.copy(physicalLoadIngressFlow = true).coreParams }
    }

    test("actual DTA accepts nomination only at the original certified non-flow checked boundary") {
        def adapter(p: OooParams, certified: Boolean, checked: Boolean = true,
            hitFlow: Boolean = true): DataTranslationAdapter =
            new DataTranslationAdapter(p, registerCheckedRequests = checked, translationHitFlow = hitFlow,
                alignedNextLinePmp = p.alignedNextLinePmp, factorCheckedNextAllowed = p.factorCheckedNextAllowed,
                certifiedLoadIngress = certified)
        val oldFir = ChiselStage.emitCHIRRTL(adapter(control.config.coreParams, true))
        val newFir = ChiselStage.emitCHIRRTL(adapter(candidate.config.coreParams, true))
        assert(!oldFir.contains("raw payload nomination cannot displace older registered or translated work"))
        assert(newFir.contains("raw payload nomination cannot displace older registered or translated work"))
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
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(adapter(candidate.config.coreParams, true, true, false))
        }
    }

    test("actual fifth tile retains the exact policy, physical safe range and complete producer integration") {
        def emit(config: FpgaNextConfig, policy: Option[CommonA1MemoryProfile],
            ranges: Seq[SideEffectFreeFetchRange]): String =
            ChiselStage.emitCHIRRTL(new CommonA1CpuTile(config,
                memoryProfile = policy, sideEffectFreeFetchRanges = ranges))
        val tile = emit(candidate.config, candidate.memoryProfile, ram)
        assert(tile.contains("module CommonA1CpuTile"))
        assert(tile.contains("module FloatingPointMemoryPipeline"))
        assert(tile.contains("module RegisteredRequestQueue"))
        assert(tile.contains("module DualWriterRobCompletionData"))
        assert(tile.contains("raw payload nomination cannot displace older registered or translated work"))
        intercept[IllegalArgumentException] { emit(candidate.config, None, ram) }
        intercept[IllegalArgumentException] { emit(candidate.config, control.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(control.config, candidate.memoryProfile, ram) }
        intercept[IllegalArgumentException] { emit(candidate.config, candidate.memoryProfile, Seq.empty) }
    }
}
