package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

/** Selection and identity tests only. Component/CPU behavior is a separate gate. */
class CommonA1CpuSpecSpec extends AnyFunSuite {
    private val profile = CommonCpuProfile.A1
    private val boundary = profile.boundary

    test("omitted CPU specification preserves existing public and experimental resolution") {
        for (p <- Seq(CommonCpuProfile.A1, CommonCpuProfile.A1Boot50, CommonCpuProfile.I1)) {
            assert(CommonA1CpuSpec.resolve(p, None, None, p.boundary) ==
                CommonA1ExperimentalSelection.config(p, None))
        }
        for (selection <- CommonA1ExperimentalSelection.all) {
            assert(CommonA1CpuSpec.resolve(profile, Some(selection), None, boundary) == selection.rebuild.config)
        }
        val identity = CommonCpuMicroarchitectureIdentity.build(profile, None, boundary)
        assert(identity("microarchitectureProfile").str == "selected")
        assert(identity("qualification").str == "PUBLIC_UNCHANGED_NOT_TIMING_QUALIFIED")
        assert(!identity.obj.contains("requestedCpuSpec"))
    }

    test("explicit LSU owner capacities change only the existing CPU capacity parameter") {
        val before = profile.fpga
        for (owners <- Seq(2, 4)) {
            val actual = CommonA1CpuSpec.resolve(profile, None, Some(CommonA1CpuSpec(owners)), boundary)
            assert(actual == before.copy(lsuEntries = owners))
            assert(actual.coreParams == before.coreParams.copy(memoryEntries = owners))
            assert(actual.coreParams.robEntries == 16 && actual.coreParams.physicalRegs == 48)
            assert(actual.coreParams.renameWidth == 2 && actual.coreParams.completionWidth == 2 &&
                actual.coreParams.commitWidth == 2 && actual.issueWidth == 2)
            assert(actual.coreParams.storeBufferEntries == 2 && actual.isaProfile == "rv64gc")
            assert(actual.cache == before.cache && actual.ddr == before.ddr && actual.network == before.network)
        }
        assert(CommonA1CpuSpec.resolve(profile, None, Some(CommonA1CpuSpec(2)), boundary) == before)
    }

    test("explicit specification rejects incompatible family clock experiment and runtime combinations") {
        val spec = Some(CommonA1CpuSpec(4))
        for (p <- Seq(CommonCpuProfile.I1, CommonCpuProfile.A1Boot50)) {
            intercept[IllegalArgumentException] { CommonA1CpuSpec.resolve(p, None, spec, p.boundary) }
        }
        for (selection <- CommonA1ExperimentalSelection.all) {
            intercept[IllegalArgumentException] {
                CommonA1CpuSpec.resolve(profile, Some(selection), spec, boundary)
            }
        }
        intercept[IllegalArgumentException] {
            CommonA1CpuSpec.resolve(profile, None, spec, boundary, experimentalRuntime = true)
        }
        for (b <- Seq(boundary.copy(runtimeMaintenance = true),
            boundary.copy(runtimeMaintenance = true, runtimeCancellation = true),
            boundary.copy(runtimeMaintenance = true, runtimeCancellation = true, runtimeInterruptHold = true))) {
            intercept[IllegalArgumentException] { CommonA1CpuSpec.resolve(profile, None, spec, b) }
        }
    }

    test("the explicit capacity parser accepts only the two supported owner counts") {
        assert(CommonA1CpuSpec.lsuOption("2") == CommonA1CpuSpec(2))
        assert(CommonA1CpuSpec.lsuOption("4") == CommonA1CpuSpec(4))
        for (text <- Seq("", "0", "1", "3", "8", "auto")) {
            intercept[IllegalArgumentException] { CommonA1CpuSpec.lsuOption(text) }
        }
        for (owners <- Seq(0, 1, 3, 8)) {
            intercept[IllegalArgumentException] { CommonA1CpuSpec(owners) }
        }
    }

    test("effective CPU identity tracks capacity without changing shared fabric or peripheral policy") {
        val ordinary = CommonCpuMicroarchitectureIdentity.build(profile, None, boundary)
        val identities = Seq(2, 4).map { owners =>
            val identity = CommonCpuMicroarchitectureIdentity.build(profile, None, boundary,
                cpuSpec = Some(CommonA1CpuSpec(owners)))
            assert(identity("effectiveCore")("memoryEntries").str == owners.toString)
            assert(identity("requestedCpuSpec")("lsuOwners").str == owners.toString)
            assert(identity("sharedFabricConfig") == ordinary("sharedFabricConfig"))
            assert(identity("qualification").str == "EXPLICIT_CPU_SPEC_NOT_CPU_BEHAVIOR_QUALIFIED")
            assert(identity("microarchitectureProfile").str == s"generic-lsu-owners-$owners")
            identity
        }
        assert((ordinary +: identities).map(_("identitySha256").str).distinct.size == 3)
        assert(profile.fpga.coreParams.memoryEntries == 2)
        assert(CommonPeripheralConfig(jtagDownload = false).features ==
            CommonPeripheralConfig().features.copy(jtagDownload = false))
    }
}
