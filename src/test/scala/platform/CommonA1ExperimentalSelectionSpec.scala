package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

/** Pure selection/identity contracts. Whole-platform elaborations and native
  * behavior are separate bounded checks, not hidden inside this suite.
  */
class CommonA1ExperimentalSelectionSpec extends AnyFunSuite {
    private val boundary = CommonCpuTilePortParams()

    test("candidate compile binding rejects a successful but unbound legacy receipt") {
        val path = java.nio.file.Files.createTempFile("a1-unbound-compile-", ".json")
        try {
            java.nio.file.Files.writeString(path, "{\"exit\":0}")
            val failure = intercept[IllegalArgumentException] {
                CommonCpuMicroarchitectureIdentity.verifyCompileReceipt(path, java.nio.file.Paths.get("."))
            }
            assert(failure.getMessage.contains("legacy exit-only rejected"))
        } finally java.nio.file.Files.delete(path)
    }

    test("default A1 remains public Selected and experiments change only the selected tile") {
        val public = CommonCpuProfile.A1.fpga
        assert(CommonA1ExperimentalSelection.config(CommonCpuProfile.A1, None) == public)
        assert(CommonA1ExperimentalSelection.memoryProfile(None).isEmpty)
        assert(public.coreParams.completionTopology == "legacy" && public.fetchTransactionSlots == 1)
        assert(!public.circularFetchPayload && !public.completedCanonicalStoreForwarding)
        for (selection <- CommonA1ExperimentalSelection.all; profile <- Seq(CommonCpuProfile.A1, CommonCpuProfile.A1Boot50)) {
            CommonA1ExperimentalSelection.validate(profile, Some(selection), boundary, experimentalRuntime = false)
            val actual = CommonA1ExperimentalSelection.config(profile, Some(selection))
            assert(actual == selection.rebuild.config)
            assert(CommonA1ExperimentalSelection.memoryProfile(Some(selection)) == selection.rebuild.memoryProfile)
            assert(actual.coreParams.completionTopology == "dual-owner" && actual.fetchTransactionSlots == 2)
            assert(actual.coreParams.branchResolutionTopology == "execution-mailbox" && actual.circularFetchPayload)
            assert(actual.completedCanonicalStoreForwarding == (selection == CommonA1ExperimentalSelection.FullR1M3))
            assert(!actual.registeredDataTranslation && actual.ddr == public.ddr && actual.network == public.network)
            assert(profile.fpga == public && profile.boundary == boundary)
        }
        assert(CommonCpuProfile.A1.cpuHz == 100000000 && CommonCpuProfile.A1Boot50.cpuHz == 50000000)
        assert(CommonCpuProfile.A1.fabricHz == 250000000 && CommonCpuProfile.A1Boot50.fabricHz == 50000000)
        assert(CommonCpuProfile.A1.clocks.timebaseHz == 250000000 && CommonCpuProfile.A1Boot50.clocks.timebaseHz == 250000000)
    }

    test("wrong family, unknown candidate, new clock tuples and incompatible boundary fail closed") {
        val selected = Some(CommonA1ExperimentalSelection.FullR1M3)
        intercept[IllegalArgumentException] { CommonA1ExperimentalSelection.named("selected") }
        intercept[IllegalArgumentException] { CommonA1ExperimentalSelection.named("full-m2-r1") }
        intercept[IllegalArgumentException] {
            CommonA1ExperimentalSelection.validate(CommonCpuProfile.I1, selected, boundary, false)
        }
        intercept[IllegalArgumentException] { CommonCpuProfile.named("a1", "performance300-static") }
        intercept[IllegalArgumentException] { CommonCpuProfile.named("a1", "boot50-dynamic") }
        intercept[IllegalArgumentException] {
            CommonA1ExperimentalSelection.validate(CommonCpuProfile("a1",
                CommonClockConfig(300000000, 250000000, 250000000)), selected, boundary, false)
        }
        intercept[IllegalArgumentException] {
            CommonA1ExperimentalSelection.validate(CommonCpuProfile.A1, selected, boundary, true)
        }
        intercept[IllegalArgumentException] {
            CommonA1ExperimentalSelection.validate(CommonCpuProfile.A1Boot50, selected, boundary, true)
        }
        intercept[IllegalArgumentException] {
            CommonA1ExperimentalSelection.validate(CommonCpuProfile.A1Boot50, selected,
                boundary.copy(runtimeMaintenance = true, runtimeCancellation = true, runtimeInterruptHold = true), false)
        }
        intercept[IllegalArgumentException] {
            CommonA1ExperimentalSelection.validate(CommonCpuProfile.A1, selected,
                boundary.copy(scalarOwnerBits = 5), false)
        }
    }

    test("identity separates same-source CPU selections, runtime contexts and unchanged shared fabric") {
        val public = CommonCpuMicroarchitectureIdentity.build(CommonCpuProfile.A1, None, boundary)
        val r1 = CommonCpuMicroarchitectureIdentity.build(CommonCpuProfile.A1,
            Some(CommonA1ExperimentalSelection.FullR1), boundary)
        val m3 = CommonCpuMicroarchitectureIdentity.build(CommonCpuProfile.A1,
            Some(CommonA1ExperimentalSelection.FullR1M3), boundary)
        assert(Seq(public, r1, m3).map(_("identitySha256").str).distinct.size == 3)
        assert(Seq(public, r1, m3).map(_("sharedFabricConfig")).distinct.size == 1)
        assert(m3("effectiveCore")("memoryEntries").str == "4")
        assert(m3("effectiveConfig")("_derived")("instructionCacheLines").str == "512")
        assert(m3("memoryProfile").str == "experimental-memory-parallel")
        assert(m3("qualification").str == "EXPERIMENTAL_NOT_TIMING_QUALIFIED")
        val runtimeBoundary = boundary.copy(runtimeMaintenance = true, runtimeCancellation = true, runtimeInterruptHold = true)
        val runtime = CommonCpuMicroarchitectureIdentity.build(CommonCpuProfile.A1Boot50,
            Some(CommonA1ExperimentalSelection.FullR1M3), runtimeBoundary, experimentalRuntime = true)
        assert(runtime("identitySha256") != m3("identitySha256"))
        assert(runtime("runtimeMode").str == "experimental-a1-runtime")
        assert(runtime("nominalClocks")("cpuHz").str == "50000000")
        assert(runtime("nominalClocks")("fabricHz").str == "50000000")
        assert(runtime("nominalClocks")("timebaseHz").str == "250000000")
        assert(m3("nominalClocks")("cpuHz").str == "100000000")
        val same = CommonCpuMicroarchitectureIdentity.build(CommonCpuProfile.A1,
            Some(CommonA1ExperimentalSelection.FullR1M3), boundary)
        assert(same == m3)
        assert(CommonCpuProfile.A1Boot50.cmu == CommonCpuProfile.I1Boot50Dynamic.cmu)
        assert(CommonCpuProfile.A1Boot50.fpga.network == CommonCpuProfile.I1Boot50Dynamic.fpga.network)
    }
}
