package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ControlTimingSpec extends AnyFunSuite {
    test("control candidate preserves fabric and storage, with stable default unchanged") {
        val p = BoardSocConfig.timingParams("staged-control")
        val old = BoardSocConfig.timingParams("staged-fabric")
        assert(BoardSocConfig.timingProfile == "early-issue")
        assert(p.renameWidth == 2 && p.issueWidth == 2 && p.commitWidth == 2)
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2 && p.storeBufferEntries == 2)
        assert(p.registeredLoadReplay && p.registeredRobRetirement && p.precompleteMispredictedBranch)
        assert(p.parallelRenameAdmission && p.stableFetchFaultMetadata)
        assert(!old.parallelRenameAdmission && !old.stableFetchFaultMetadata && !old.precompleteMispredictedBranch)
    }
    test("capacity tree has no state or added pipeline cycle") {
        for (width <- Seq(1, 2, 4, 6)) {
            val rtl = ChiselStage.emitCHIRRTL(new RenameAllocationCapacity(width, 48))
            assert(!rtl.linesIterator.exists(_.trim.startsWith("reg ")))
        }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new RenameAllocationCapacity(7, 48)) }
    }
    test("only opt-in ledger elaborates parallel capacity admission") {
        val p = OooParams(robEntries = 16, physicalRegs = 48, parallelRenameAdmission = true)
        assert(ChiselStage.emitCHIRRTL(new RenameRob(p)).contains("module RenameAllocationCapacity"))
        assert(!ChiselStage.emitCHIRRTL(new RenameRob(p.copy(parallelRenameAdmission = false)))
            .contains("module RenameAllocationCapacity"))
    }
}
