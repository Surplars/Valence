package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

class M2R1ProfileSpec extends AnyFunSuite {
    test("M2 and R1 are independent explicit differences, not new Selected defaults") {
        val control = CommonA1RebuildProfile.FullCandidate.config
        assert(!control.registeredDataTranslation && !control.circularFetchPayload && control.translationHitFlow)
        assert(!CommonCpuProfile.A1.fpga.registeredDataTranslation && !CommonCpuProfile.A1.fpga.circularFetchPayload)
        for ((profile, m2, r1) <- Seq(
            (CommonA1RebuildProfile.FullCandidate, false, false),
            (CommonA1RebuildProfile.FullM2, true, false),
            (CommonA1RebuildProfile.FullR1, false, true),
            (CommonA1RebuildProfile.FullM2R1, true, true))) {
            val config = profile.config
            assert(config == control.copy(translationHitFlow = !m2,
                registeredDataTranslation = m2, circularFetchPayload = r1))
            assert(config.coreParams.registeredDataTranslation == m2 && config.coreParams.circularFetchPayload == r1)
            assert(config.coreParams.copy(registeredDataTranslation = false, circularFetchPayload = false) ==
                control.coreParams)
            profile.memoryProfile.get.validate(config, CommonCpuTilePortParams())
            intercept[IllegalArgumentException] { config.managedBoard() }
        }
    }
    test("conflicting M2 result routes and stale profile labels are rejected") {
        val base = CommonA1RebuildProfile.FullCandidate.config
        val m2 = CommonA1RebuildProfile.FullM2.config
        intercept[IllegalArgumentException] { base.copy(registeredDataTranslation = true) }
        intercept[IllegalArgumentException] { m2.copy(translationHitFlow = true) }
        intercept[IllegalArgumentException] {
            CommonA1MemoryProfile.ExperimentalMemoryParallel.validate(m2, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] {
            CommonA1MemoryProfile.ExperimentalRegisteredTranslation.validate(base, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] { m2.coreParams.copy(canonicalVirtualStoreOverlap = false) }
        intercept[IllegalArgumentException] { m2.coreParams.copy(registeredTranslationHeads = false) }
        intercept[IllegalArgumentException] { m2.coreParams.copy(precheckedDataRequestFlow = true) }
        intercept[IllegalArgumentException] { base.coreParams.copy(circularFetchPayload = true, registeredFetchPacket = false) }
    }
}
