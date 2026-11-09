package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

/** The timing candidate is explicit; it never promotes a public board identity. */
class CombinedA1OptimizationSpec extends AnyFunSuite {
    test("public default geometry and new storage controls remain unchanged") {
        val p = CommonCpuProfile.A1.fpga.coreParams
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(p.renameWidth == 2 && p.commitWidth == 2)
        assert(p.indirectTargetEntries == 0 && !p.bankedIndirectStorage && !p.compactIssueImmediates)
    }
    test("explicit combined selection reaches core parameters without changing other capabilities") {
        val base = CommonCpuProfile.A1.fpga
        val selected = base.copy(indirectTargetEntries = 16, bankedIndirectStorage = true,
            compactIssueImmediates = true)
        val p = selected.coreParams
        assert(p.indirectTargetEntries == 16 && p.bankedIndirectStorage && p.compactIssueImmediates)
        assert(p.compressedInstructions && p.registeredPredictionTraining && p.bankedIssuePayload)
        assert(p.copy(indirectTargetEntries = 0, bankedIndirectStorage = false,
            compactIssueImmediates = false) == base.coreParams)
        assert(selected.name != base.name)
    }
    test("efficiency4 final configuration retains its exact memory policy and fabric geometry") {
        val mode = "efficiency4-candidate"
        val config = platform.CombinedA1FabricTimingConfig.cpu(mode)
        val boundary = platform.CombinedA1FabricTimingConfig.boundary
        platform.CombinedA1FabricTimingConfig.memoryProfile(mode).get.validate(config, boundary)
        val p = config.coreParams
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4)
        assert(p.bankedIndirectStorage && p.compactIssueImmediates && p.indirectTargetEntries == 16)
        assert(p.coexistingPhysicalLoadIngress && p.bankedRobCompletionData && p.decodedNaturalPmp)
        val fabric = platform.CombinedA1FabricTimingConfig.fabric(mode)
        assert(fabric.completionFlow && fabric.readOverlap && fabric.probeOverlap)
        assert(fabric.fpga.ddr.maxOutstanding == 4 && fabric.fpga.ddr.maxOutstandingWrites == 2)
    }
    test("MUL capture extends the delivered candidate by exactly one capability") {
        val before = platform.CombinedA1FabricTimingConfig.cpu("efficiency4-candidate")
        val after = platform.CombinedA1FabricTimingConfig.cpu("efficiency4-mul-candidate")
        assert(after.copy(registeredMulLoadOperandCapture = false) == before)
        assert(after.coreParams.copy(registeredMulLoadOperandCapture = false) == before.coreParams)
        assert(after.bankedIndirectStorage && after.compactIssueImmediates && after.indirectTargetEntries == 16)
        assert(!after.contextOwnedInstructionPrefetch && !after.loadPayloadNomination)
        val policy = platform.CombinedA1FabricTimingConfig.memoryProfile("efficiency4-mul-candidate").get
        assert(policy == CommonA1MemoryProfile.ExperimentalMulLoadOperandCapture)
        policy.validate(after, platform.CombinedA1FabricTimingConfig.boundary)
        assert(platform.CombinedA1FabricTimingConfig.fabric("efficiency4-candidate") ==
            platform.CombinedA1FabricTimingConfig.fabric("efficiency4-mul-candidate"))
        assert(platform.CombinedA1FabricTimingConfig.safeFetchRanges("efficiency4-candidate") ==
            platform.CombinedA1FabricTimingConfig.safeFetchRanges("efficiency4-mul-candidate"))
    }
    test("default identity omits only new inactive fields while experiments stay explicit") {
        val base = CommonCpuProfile.A1.fpga
        val before = platform.CommonCpuMicroarchitectureIdentity.configuration(base).obj
        assert(!before.contains("compactIssueImmediates") && !before.contains("bankedIndirectStorage") &&
            !before.contains("indirectTargetEntries"))
        val selected = base.copy(indirectTargetEntries = 16, bankedIndirectStorage = true,
            compactIssueImmediates = true)
        val after = platform.CommonCpuMicroarchitectureIdentity.configuration(selected).obj
        assert(after("compactIssueImmediates").str == "true" && after("bankedIndirectStorage").str == "true" &&
            after("indirectTargetEntries").str == "16")
        assert(platform.CommonCpuMicroarchitectureIdentity.value(base.coreParams).obj("indirectTargetEntries").str == "0")
    }
    test("unsupported predictor geometry and legacy board selection fail closed") {
        val p = CommonCpuProfile.A1.fpga.coreParams.copy(indirectTargetEntries = 16,
            bankedIndirectStorage = true)
        intercept[IllegalArgumentException] { p.copy(indirectTargetEntries = 32) }
        intercept[IllegalArgumentException] { p.copy(compressedInstructions = false) }
        intercept[IllegalArgumentException] { p.copy(registeredPredictionTraining = false) }
        intercept[IllegalArgumentException] { p.copy(commitWidth = 1) }
        intercept[IllegalArgumentException] {
            CommonCpuProfile.A1.fpga.copy(indirectTargetEntries = 16, bankedIndirectStorage = true).managedBoard()
        }
    }
}
