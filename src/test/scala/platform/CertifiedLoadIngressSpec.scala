package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class CertifiedLoadIngressSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3AdvisoryOwner
    private val candidate = CommonA1RebuildProfile.FullR1M3CertifiedIngress

    test("certified ingress is a separately named exact default-off descendant") {
        assert(!OooParams().certifiedLoadIngress && !FpgaNextConfig.Selected.certifiedLoadIngress)
        assert(!CommonCpuProfile.A1.fpga.certifiedLoadIngress)
        assert(candidate.config == control.config.copy(certifiedLoadIngress = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(certifiedLoadIngress = true))
        assert(candidate.name == "full-r1-m3-certified-ingress")
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        for (profile <- CommonA1RebuildProfile.all) {
            assert(profile.config.certifiedLoadIngress == Set[CommonA1RebuildProfile](candidate,
                CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5,
                CommonA1RebuildProfile.FullR1M3MulLoadOperandCaptureExperiment,
                CommonA1RebuildProfile.FullR1M3ContextFetchPrefetchExperiment).contains(profile))
            assert(profile.config.coreParams.certifiedLoadIngress == Set[CommonA1RebuildProfile](candidate,
                CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5,
                CommonA1RebuildProfile.FullR1M3MulLoadOperandCaptureExperiment,
                CommonA1RebuildProfile.FullR1M3ContextFetchPrefetchExperiment).contains(profile))
        }
        val p = candidate.config.coreParams
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
        assert(p.memoryEntries == 4 && p.storeBufferEntries == 2)
        assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
        assert(!p.physicalLoadIngressFlow && !p.registeredDataTranslation && !p.registeredRawCertifiedFlow)
        assert(p.registeredMemoryRequests && p.registeredTranslationHeads && p.combinedCheckedDataFlow)
        assert(p.orderedLsuResponseReady && p.registeredAdvisoryExclusion && p.bufferedReturnFlow)
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
    }

    test("new policy is exact and does not silently broaden any old memory policy") {
        val policy = candidate.memoryProfile.get
        assert(policy == CommonA1MemoryProfile.ExperimentalCertifiedIngress)
        policy.validate(candidate.config, CommonCpuTilePortParams())
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            intercept[IllegalArgumentException] { policy.validate(old.config, CommonCpuTilePortParams()) }
            old.memoryProfile.foreach { oldPolicy =>
                intercept[IllegalArgumentException] { oldPolicy.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
    }

    test("certified ingress cannot bypass guarded ownership or storage prerequisites") {
        intercept[IllegalArgumentException] { OooParams(certifiedLoadIngress = true) }
        val p = candidate.config.coreParams
        val bad: Seq[() => OooParams] = Seq(
            () => p.copy(registeredAdvisoryExclusion = false),
            () => p.copy(orderedLsuResponseReady = false),
            () => p.copy(guardedNaturalDataPmp = false),
            () => p.copy(registeredMemoryRequests = false),
            () => p.copy(registeredTranslationHeads = false),
            () => p.copy(combinedCheckedDataFlow = false),
            () => p.copy(physicalLoadIngressFlow = true),
            () => p.copy(registeredDataTranslation = true),
            () => p.copy(registeredRawCertifiedFlow = true),
            () => p.copy(memoryEntries = 8),
            () => p.copy(tagBits = 32))
        for (change <- bad) { intercept[IllegalArgumentException] { change() } }
    }
}
