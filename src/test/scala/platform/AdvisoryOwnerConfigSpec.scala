package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class AdvisoryOwnerConfigSpec extends AnyFunSuite {
    private val base = CommonA1RebuildProfile.FullR1M3BufferedReturnFlow
    private val owner = CommonA1RebuildProfile.FullR1M3OrderedOwnerReady
    private val combined = CommonA1RebuildProfile.FullR1M3AdvisoryOwner

    test("owner readiness and advisory supply are exact separately named default-off descendants") {
        assert(!OooParams().orderedLsuResponseReady && !OooParams().registeredAdvisoryExclusion)
        assert(!FpgaNextConfig.Selected.orderedLsuResponseReady && !FpgaNextConfig.Selected.registeredAdvisoryExclusion)
        assert(owner.config == base.config.copy(orderedLsuResponseReady = true))
        assert(combined.config == owner.config.copy(registeredAdvisoryExclusion = true))
        assert(owner.config.coreParams == base.config.coreParams.copy(orderedLsuResponseReady = true))
        assert(combined.config.coreParams == owner.config.coreParams.copy(registeredAdvisoryExclusion = true))
        for (profile <- CommonA1RebuildProfile.all) {
            assert(profile.config.orderedLsuResponseReady == Set[CommonA1RebuildProfile](owner, combined,
                CommonA1RebuildProfile.FullR1M3CertifiedIngress,
                CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5).contains(profile))
            assert(profile.config.registeredAdvisoryExclusion == Set[CommonA1RebuildProfile](combined,
                CommonA1RebuildProfile.FullR1M3CertifiedIngress,
                CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor5).contains(profile))
        }
        for (profile <- Seq(owner, combined)) {
            assert(CommonA1RebuildProfile.named(profile.name) == profile)
            val p = profile.config.coreParams
            assert(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
            assert(p.memoryEntries == 4 && p.storeBufferEntries == 2)
            assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
            assert(profile.config.cache == base.config.cache && profile.config.ddr == base.config.ddr)
        }
    }

    test("each named policy rejects every other named profile") {
        for (profile <- Seq(owner, combined)) {
            val policy = profile.memoryProfile.get
            policy.validate(profile.config, CommonCpuTilePortParams())
            for (other <- CommonA1RebuildProfile.all.filterNot(_ == profile)) {
                intercept[IllegalArgumentException] { policy.validate(other.config, CommonCpuTilePortParams()) }
                other.memoryProfile.foreach { old =>
                    intercept[IllegalArgumentException] { old.validate(profile.config, CommonCpuTilePortParams()) }
                }
            }
        }
    }

    test("unqualified readiness and advisory combinations are rejected") {
        intercept[IllegalArgumentException] { OooParams(orderedLsuResponseReady = true) }
        intercept[IllegalArgumentException] { OooParams(registeredAdvisoryExclusion = true) }
        intercept[IllegalArgumentException] { combined.config.coreParams.copy(orderedLsuResponseReady = false) }
        intercept[IllegalArgumentException] { combined.config.copy(orderedLsuResponseReady = false) }
        val p = owner.config.coreParams
        val changes: Seq[() => OooParams] = Seq(
            () => p.copy(registeredMemoryRequests = false),
            () => p.copy(bufferedReturnFlow = false),
            () => p.copy(registeredStoreResponseOwners = false),
            () => p.copy(registeredLocalStoreResponses = true),
            () => p.copy(taggedStoreReturns = true),
            () => p.copy(localTaggedResponseReady = true),
            () => p.copy(fastHeadLoadRetire = true),
            () => p.copy(fastBufferedStoreRetire = true),
            () => p.copy(loadCompletionBypass = true),
            () => p.copy(registeredLoadResultReady = true),
            () => p.copy(robEntries = 32),
            () => p.copy(memoryEntries = 8),
            () => p.copy(physicalRegs = 64),
            () => p.copy(tagBits = 32))
        for (change <- changes) { intercept[IllegalArgumentException] { change() } }
    }
}
