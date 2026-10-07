package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class DataTimingSpec extends AnyFunSuite {
    test("data candidate batches request isolation and relocated response credits without widening") {
        val p = BoardSocConfig.timingParams("staged-data")
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(p.registeredMemoryRequests && p.registeredMemoryAddress && p.registeredStoreResponseOwners)
        assert(p.registeredRobRetirement && p.registeredLoadReplay && p.precompleteMispredictedBranch)
        assert(p.parallelRenameAdmission && p.stableFetchFaultMetadata && !p.registeredLocalStoreResponses)
        assert(!BoardSocConfig.timingParams("staged-control").registeredMemoryRequests)
        assert(BoardSocConfig.timingProfile == "early-issue")
    }
    test("response credit relocation cannot silently stack or change non-flow response mode") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MachinePlatform(bufferTranslatedResponses = true))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MappedMachineCore(bufferTranslatedResponses = true))
        }
        val rtl = ChiselStage.emitCHIRRTL(new DataTimingGsim)
        assert(rtl.contains("module DataResponseBuffer") && rtl.contains("module DataRequestBuffer"))
    }
}
